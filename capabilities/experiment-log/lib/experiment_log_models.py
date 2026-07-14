"""Typed requests and durable records owned by experiment-log."""

from __future__ import annotations

from dataclasses import MISSING, asdict, dataclass, field, fields, is_dataclass
import types
from typing import Any, Literal, TypeVar, Union, cast, get_args, get_origin, get_type_hints


class ModelError(ValueError):
    pass


ModelT = TypeVar("ModelT")
ExperimentStatus = Literal["completed", "failed", "invalid"]


@dataclass(frozen=True)
class ExperimentCode:
    branch: str | None = None
    commit: str | None = None


@dataclass(frozen=True)
class ExperimentMetric:
    name: str
    value: str


@dataclass(frozen=True)
class ExperimentLogAppendRequest:
    title: str
    short_description: str
    code: ExperimentCode
    description: str
    command: str
    status: ExperimentStatus
    success: bool
    key_result: str
    metrics: list[ExperimentMetric] = field(default_factory=list)
    artifacts: list[str] = field(default_factory=list)
    work_branch: str | None = None
    notes: str | None = None


@dataclass(frozen=True)
class ExperimentLogCorrectRequest:
    experiment_id: str
    summary: str
    correction: str


@dataclass(frozen=True)
class ExperimentLogAppendResult:
    experiment_id: str


@dataclass(frozen=True)
class ExperimentLogCorrectResult:
    correction_id: str


@dataclass(frozen=True)
class ExperimentCorrection:
    correction_id: str
    created_at: str
    user_id: str
    status: Literal["corrected"]
    summary: str
    correction: str


@dataclass
class Experiment:
    schema_version: int
    kind: Literal["experiment_result"]
    experiment_id: str
    work_branch: str
    title: str
    short_description: str
    created_at: str
    user_id: str
    description: str
    code: ExperimentCode
    command: str
    status: ExperimentStatus
    success: bool
    key_result: str
    metrics: list[ExperimentMetric]
    artifacts: list[str]
    notes: str | None
    corrections: list[ExperimentCorrection] = field(default_factory=list)


def _decode(annotation: object, value: object, path: str) -> object:
    origin = get_origin(annotation)
    args = get_args(annotation)
    if origin in {Union, types.UnionType}:
        if value is None and type(None) in args:
            return None
        errors: list[str] = []
        for option in (item for item in args if item is not type(None)):
            try:
                return _decode(option, value, path)
            except ModelError as exc:
                errors.append(str(exc))
        raise ModelError(errors[0] if errors else f"{path}: invalid value")
    if origin is Literal:
        if value not in args:
            raise ModelError(f"{path}: expected one of {list(args)!r}")
        return value
    if origin is list:
        if not isinstance(value, list):
            raise ModelError(f"{path}: expected a list")
        item_type = args[0] if args else Any
        return [_decode(item_type, item, f"{path}[{index}]") for index, item in enumerate(value)]
    if isinstance(annotation, type) and is_dataclass(annotation):
        if not isinstance(value, dict):
            raise ModelError(f"{path}: expected a mapping")
        return decode_model(annotation, value, path=path)
    if annotation is bool:
        valid = type(value) is bool
    elif annotation is int:
        valid = type(value) is int
    elif annotation is float:
        valid = isinstance(value, (int, float)) and not isinstance(value, bool)
    else:
        valid = isinstance(value, annotation) if isinstance(annotation, type) else False
    if not valid:
        raise ModelError(f"{path}: expected {getattr(annotation, '__name__', annotation)}")
    return value


def decode_model(model: type[ModelT], data: dict[str, object], *, path: str = "request") -> ModelT:
    model_fields = {item.name: item for item in fields(model)}
    unknown = sorted(set(data) - set(model_fields))
    if unknown:
        raise ModelError(f"{path}: unknown field(s): {', '.join(unknown)}")

    hints = get_type_hints(model)
    values: dict[str, object] = {}
    for name, item in model_fields.items():
        if name in data:
            values[name] = _decode(hints[name], data[name], f"{path}.{name}")
        elif item.default is MISSING and item.default_factory is MISSING:
            raise ModelError(f"{path}.{name}: required field is missing")
    return model(**values)


def model_data(model: object) -> dict[str, object]:
    return cast(dict[str, object], asdict(model))
