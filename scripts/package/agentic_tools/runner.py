"""JSON/YAML command adapter for an importable structured Python tool."""

from __future__ import annotations

import argparse
import importlib
import json
import sys

import yaml

from agentic_tools.contract import PythonTool
from agentic_tools.data import record_data, record_from_data, record_schema


class ToolError(RuntimeError):
    """Raised for invalid structured tool requests."""


def load_tool(reference: str) -> type[PythonTool[object]]:
    module_name, separator, symbol_name = reference.partition(":")
    if not separator or not module_name or not symbol_name or "<locals>" in symbol_name:
        raise ToolError("tool reference must be a top-level module:Class symbol")
    value: object = importlib.import_module(module_name)
    for component in symbol_name.split("."):
        value = getattr(value, component)
    if not isinstance(value, type) or not issubclass(value, PythonTool):
        raise ToolError(f"not a PythonTool: {reference}")
    return value


def execute(reference: str, input_text: str) -> object:
    request = yaml.safe_load(input_text) or {}
    if not isinstance(request, dict):
        raise ToolError("tool request JSON/YAML must be a mapping")
    tool = record_from_data(load_tool(reference), request, reject_unknown=True)
    return tool.execute()


def cli() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tool", help="Importable module:PythonTool symbol")
    parser.add_argument(
        "--schema",
        action="store_true",
        help="Print the tool input JSON Schema without executing it",
    )
    args = parser.parse_args()
    try:
        if args.schema:
            print(json.dumps(record_schema(load_tool(args.tool)), sort_keys=True))
        else:
            result = execute(args.tool, sys.stdin.read())
            print(json.dumps(record_data(result), sort_keys=True))
    except (
        ToolError,
        ImportError,
        AttributeError,
        RuntimeError,
        TypeError,
        ValueError,
        yaml.YAMLError,
    ) as error:
        print(f"agentic-tool: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(cli())
