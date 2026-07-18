from __future__ import annotations

from dataclasses import fields, is_dataclass
from pathlib import Path
import types
import sys
from typing import ClassVar, Literal, Union, get_args, get_origin, get_type_hints


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts" / "package"))
sys.path.insert(0, str(REPO_ROOT / "capabilities" / "experiment-log" / "lib"))
sys.path.insert(0, str(REPO_ROOT / "capabilities" / "experiment-log" / "package"))

from agentic_tools import PythonTool, Record  # noqa: E402
from experiment_log.tools import (  # noqa: E402
    ExperimentCode as ToolExperimentCode,
    ExperimentLogAppendResult as ToolAppendResult,
    ExperimentLogAppendTool,
    ExperimentLogCorrectResult as ToolCorrectResult,
    ExperimentLogCorrectTool,
    ExperimentLogSummaryTool,
    ExperimentMetric as ToolExperimentMetric,
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
    if isinstance(annotation, type) and (is_dataclass(annotation) or issubclass(annotation, Record)):
        return ("record", {name: shape(value) for name, value in record_fields(annotation).items()})
    return annotation


def test_native_tool_fields_match_experiment_log_domain_models() -> None:
    assert issubclass(ExperimentLogAppendTool, PythonTool)
    assert issubclass(ExperimentLogCorrectTool, PythonTool)
    assert issubclass(ExperimentLogSummaryTool, PythonTool)

    exact_pairs = [
        (ExperimentCode, ToolExperimentCode),
        (ExperimentMetric, ToolExperimentMetric),
        (ExperimentLogAppendResult, ToolAppendResult),
        (ExperimentLogCorrectResult, ToolCorrectResult),
    ]
    for domain_model, tool_record in exact_pairs:
        assert shape(domain_model) == shape(tool_record)

    append_domain = record_fields(ExperimentLogAppendRequest)
    append_tool = record_fields(ExperimentLogAppendTool)
    append_shape = {
        name: shape(value)
        for name, value in append_tool.items()
        if name != "project_dir"
    }
    assert append_shape == {
        name: shape(value) for name, value in append_domain.items()
    }

    correction_domain = record_fields(ExperimentLogCorrectRequest)
    correction_tool = record_fields(ExperimentLogCorrectTool)
    assert {
        name: shape(value)
        for name, value in correction_tool.items()
        if name not in {"project_dir", "work_branch"}
    } == {name: shape(value) for name, value in correction_domain.items()}
