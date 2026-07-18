"""Discover structured tools declared by enabled capability packages."""

from __future__ import annotations

from dataclasses import dataclass
import importlib
import os
from pathlib import Path
import re
import tomllib

from agentic_tools.contract import PythonTool


TOOL_NAME = re.compile(r"^[a-z][a-z0-9_]*$")


@dataclass(frozen=True)
class ToolRegistration:
    name: str
    reference: str
    tool_type: type[PythonTool[object]]


def load_python_tool(reference: str) -> type[PythonTool[object]]:
    module_name, separator, symbol_name = reference.partition(":")
    if not separator or not module_name or not symbol_name or "<locals>" in symbol_name:
        raise ValueError(f"tool reference must be a top-level module:Class symbol: {reference!r}")
    value: object = importlib.import_module(module_name)
    for component in symbol_name.split("."):
        value = getattr(value, component)
    if not isinstance(value, type) or not issubclass(value, PythonTool):
        raise TypeError(f"registered tool is not a PythonTool: {reference}")
    return value


def package_roots(value: str | None = None) -> list[Path]:
    raw = os.environ.get("AR_TOOL_PATH", "") if value is None else value
    return [Path(item).expanduser().resolve() for item in raw.split(os.pathsep) if item]


def discover_tools(value: str | None = None) -> dict[str, ToolRegistration]:
    registrations: dict[str, ToolRegistration] = {}
    for package_root in package_roots(value):
        manifest_path = package_root.parent / "capability.toml"
        if not manifest_path.is_file():
            continue
        document = tomllib.loads(manifest_path.read_text(encoding="utf-8"))
        declared = document.get("tools", {})
        if not isinstance(declared, dict):
            raise ValueError(f"{manifest_path}: tools must be a TOML table")
        for name, raw_registration in declared.items():
            if not TOOL_NAME.fullmatch(name):
                raise ValueError(f"{manifest_path}: invalid MCP tool name: {name!r}")
            if isinstance(raw_registration, str):
                reference = raw_registration
            elif isinstance(raw_registration, dict) and isinstance(
                raw_registration.get("implementation"), str
            ):
                reference = raw_registration["implementation"]
            else:
                raise ValueError(
                    f"{manifest_path}: tools.{name} must be a reference string or "
                    "a table containing implementation"
                )
            if name in registrations:
                previous = registrations[name]
                raise ValueError(
                    f"duplicate MCP tool name {name!r}: {previous.reference} and {reference}"
                )
            registrations[name] = ToolRegistration(
                name=name,
                reference=reference,
                tool_type=load_python_tool(reference),
            )
    return registrations
