"""CLI entrypoint for one registered model-free ExecutableWorkflow."""

from __future__ import annotations

import argparse
import importlib
import json
import sys

import yaml

from agentic_workflows.contract import ExecutableWorkflow
from agentic_workflows.execution import (
    OperationExecutionError,
    OperationExecutor,
    record_data,
    record_from_data,
)


def load_symbol(reference: str) -> type[ExecutableWorkflow[object]]:
    module_name, separator, symbol_name = reference.partition(":")
    if not separator or not module_name or not symbol_name or "<locals>" in symbol_name:
        raise OperationExecutionError("workflow reference must be a top-level module:Class symbol")
    value: object = importlib.import_module(module_name)
    for component in symbol_name.split("."):
        value = getattr(value, component)
    if not isinstance(value, type) or not issubclass(value, ExecutableWorkflow):
        raise OperationExecutionError(f"not an ExecutableWorkflow: {reference}")
    return value


def execute(reference: str) -> None:
    workflow_type = load_symbol(reference)
    request = yaml.safe_load(sys.stdin.read()) or {}
    if not isinstance(request, dict):
        raise OperationExecutionError("workflow request YAML must be a mapping")
    workflow = record_from_data(workflow_type, request, reject_unknown=True)
    with OperationExecutor() as executor:
        result = executor.run(workflow)
    print(json.dumps(record_data(result), sort_keys=True))


def cli() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("workflow", help="Importable module:ExecutableWorkflow symbol")
    args = parser.parse_args()
    try:
        execute(args.workflow)
    except (OperationExecutionError, ImportError, AttributeError, RuntimeError, TypeError, ValueError) as error:
        print(f"imperative-workflows-run: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(cli())
