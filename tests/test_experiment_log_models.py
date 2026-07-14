from __future__ import annotations

from dataclasses import fields, is_dataclass
from pathlib import Path
import types
import sys
from typing import ClassVar, Literal, Union, get_args, get_origin, get_type_hints


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "capabilities" / "experiment-log" / "lib"))
sys.path.insert(0, str(REPO_ROOT / "capabilities" / "experiment-log" / "package"))
sys.path.insert(0, str(REPO_ROOT / "capabilities" / "imperative-workflows" / "package"))

from agentic_workflows.contract import WorkflowRecord  # noqa: E402
from agentic_workflows.research.experiment_log import (  # noqa: E402
    ExperimentCode as WorkflowExperimentCode,
    ExperimentLogAppendResult as WorkflowAppendResult,
    ExperimentLogAppendTool,
    ExperimentLogCorrectResult as WorkflowCorrectResult,
    ExperimentLogCorrectTool,
    ExperimentMetric as WorkflowExperimentMetric,
)
from experiment_log_models import (  # noqa: E402
    ExperimentCode,
    ExperimentLogAppendRequest,
    ExperimentLogAppendResult,
    ExperimentLogCorrectRequest,
    ExperimentLogCorrectResult,
    ExperimentMetric,
)


def record_fields(record: type[object]) -> dict[str, object]:
    hints = get_type_hints(record)
    if is_dataclass(record):
        return {item.name: hints[item.name] for item in fields(record)}
    return {
        name: hints[name]
        for name in record.__annotations__
        if get_origin(hints[name]) is not ClassVar
    }


def shape(annotation: object) -> object:
    origin = get_origin(annotation)
    args = get_args(annotation)
    if origin in {Union, types.UnionType}:
        return ("union", tuple(shape(item) for item in args))
    if origin is Literal:
        return ("literal", args)
    if origin is list:
        return ("list", shape(args[0]))
    if isinstance(annotation, type) and (is_dataclass(annotation) or issubclass(annotation, WorkflowRecord)):
        return ("record", {name: shape(value) for name, value in record_fields(annotation).items()})
    return annotation


def test_agent_adapter_matches_experiment_log_command_contract() -> None:
    pairs = [
        (ExperimentCode, WorkflowExperimentCode),
        (ExperimentMetric, WorkflowExperimentMetric),
        (ExperimentLogAppendRequest, ExperimentLogAppendTool),
        (ExperimentLogCorrectRequest, ExperimentLogCorrectTool),
        (ExperimentLogAppendResult, WorkflowAppendResult),
        (ExperimentLogCorrectResult, WorkflowCorrectResult),
    ]
    for command_model, workflow_adapter in pairs:
        assert shape(command_model) == shape(workflow_adapter)
