"""Strict JSON/YAML decoding for typed tool records."""

from __future__ import annotations

from dataclasses import MISSING, fields, is_dataclass
import types
from typing import Any, Literal, Union, get_args, get_origin, get_type_hints

from agentic_tools.contract import Record


def annotation_schema(annotation: object) -> dict[str, object]:
    """Render the supported annotation subset as JSON Schema."""

    if annotation in {Any, object}:
        return {}
    origin = get_origin(annotation)
    args = get_args(annotation)
    if origin is Literal:
        return {"enum": list(args)}
    if origin in {list, tuple}:
        return {
            "type": "array",
            "items": annotation_schema(args[0] if args else Any),
        }
    if origin in {Union, types.UnionType}:
        return {"anyOf": [annotation_schema(candidate) for candidate in args]}
    if isinstance(annotation, type) and issubclass(annotation, Record):
        return record_schema(annotation)
    if annotation is type(None):
        return {"type": "null"}
    primitive = {str: "string", int: "integer", float: "number", bool: "boolean"}
    if annotation in primitive:
        return {"type": primitive[annotation]}
    return {}


def record_schema(record_type: type[Record]) -> dict[str, object]:
    """Render a record's annotations and Value metadata as JSON Schema."""

    hints = get_type_hints(record_type)
    properties: dict[str, object] = {}
    required: list[str] = []
    for item in fields(record_type):
        field_schema = annotation_schema(hints.get(item.name, item.type))
        description = item.metadata.get("description")
        guidance = item.metadata.get("guidance")
        if description:
            field_schema["description"] = description
        if guidance:
            field_schema["x-guidance"] = guidance
        properties[item.name] = field_schema
        if item.default is MISSING and item.default_factory is MISSING:
            required.append(item.name)
    schema: dict[str, object] = {
        "type": "object",
        "properties": properties,
        "additionalProperties": False,
    }
    if required:
        schema["required"] = required
    description = (record_type.__doc__ or "").strip()
    if description:
        schema["description"] = description
    return schema


def record_data(value: object) -> object:
    """Convert typed records into JSON/YAML-compatible values."""

    if isinstance(value, Record) and is_dataclass(value):
        return {
            item.name: record_data(getattr(value, item.name))
            for item in fields(value)
            if getattr(value, item.name) is not None
        }
    if isinstance(value, (list, tuple)):
        return [record_data(item) for item in value]
    if isinstance(value, dict):
        return {str(key): record_data(item) for key, item in value.items() if item is not None}
    return value


def decode_value(
    annotation: object,
    value: object,
    *,
    reject_unknown_records: bool = False,
) -> object:
    """Decode one JSON-compatible value according to a Python annotation."""

    if annotation in {Any, object}:
        return value
    origin = get_origin(annotation)
    args = get_args(annotation)
    if origin is Literal:
        if value not in args:
            raise ValueError(f"expected one of {args!r}, got {value!r}")
        return value
    if origin in {list, tuple}:
        if not isinstance(value, (list, tuple)):
            raise TypeError(f"expected an array, got {type(value).__name__}")
        item_type = args[0] if args else Any
        decoded = [
            decode_value(item_type, item, reject_unknown_records=reject_unknown_records)
            for item in value
        ]
        return tuple(decoded) if origin is tuple else decoded
    if origin in {Union, types.UnionType}:
        if value is None and type(None) in args:
            return None
        errors: list[Exception] = []
        for candidate in args:
            if candidate is type(None):
                continue
            try:
                return decode_value(
                    candidate,
                    value,
                    reject_unknown_records=reject_unknown_records,
                )
            except (TypeError, ValueError) as error:
                errors.append(error)
        detail = str(errors[-1]) if errors else f"does not match {annotation!r}"
        raise TypeError(detail)
    if isinstance(annotation, type) and issubclass(annotation, Record):
        if not isinstance(value, dict):
            raise TypeError(f"{annotation.__name__} requires an object")
        return record_from_data(
            annotation,
            value,
            reject_unknown=reject_unknown_records,
        )
    if annotation is type(None):
        if value is not None:
            raise TypeError(f"expected null, got {type(value).__name__}")
        return None
    if annotation in {str, int, float, bool}:
        valid = isinstance(value, annotation)
        if annotation in {int, float} and isinstance(value, bool):
            valid = False
        if annotation is float and isinstance(value, int) and not isinstance(value, bool):
            return float(value)
        if not valid:
            raise TypeError(f"expected {annotation.__name__}, got {type(value).__name__}")
    return value


def record_from_data(
    record_type: type[Record],
    data: dict[str, object],
    *,
    reject_unknown: bool = False,
) -> Record:
    """Construct one typed record from a decoded request mapping."""

    if not is_dataclass(record_type):
        raise TypeError(f"record is not a dataclass: {record_type.__name__}")
    field_names = {item.name for item in fields(record_type)}
    unknown = sorted(set(data) - field_names)
    if reject_unknown and unknown:
        raise TypeError(f"unexpected {record_type.__name__} fields: {', '.join(unknown)}")
    missing = [
        item.name
        for item in fields(record_type)
        if item.name not in data
        and item.default is MISSING
        and item.default_factory is MISSING
    ]
    if missing:
        raise TypeError(f"missing required {record_type.__name__} fields: {', '.join(missing)}")
    hints = get_type_hints(record_type)
    values = {
        item.name: decode_value(
            hints.get(item.name, item.type),
            data[item.name],
            reject_unknown_records=reject_unknown,
        )
        for item in fields(record_type)
        if item.name in data
    }
    return record_type(**values)
