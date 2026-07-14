from dataclasses import asdict, fields, is_dataclass
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_DIR = REPO_ROOT / "docs" / "imperative-workflows"
sys.path.insert(0, str(WORKFLOW_DIR))

from workflow_runtime import (
    ArgvTool,
    Value,
    WorkflowRecord,
    WorkflowTool,
    YAMLArgvTool,
    record_data,
    record_json_schema,
)  # noqa: E402


def test_workflow_record_auto_applies_dataclass_behavior() -> None:
    class Record(WorkflowRecord):
        name: str
        count: int = 0

    record = Record(name="demo")

    assert is_dataclass(Record)
    assert asdict(record) == {"name": "demo", "count": 0}


def test_workflow_record_subclasses_register_new_fields() -> None:
    class ParentRecord(WorkflowRecord):
        parent: str

    class ChildRecord(ParentRecord):
        child: str = Value("Child value")

    assert [field.name for field in fields(ChildRecord)] == ["parent", "child"]
    assert ChildRecord(parent="a", child="b").child == "b"


def test_record_data_recurses_through_nested_records_and_lists() -> None:
    class Child(WorkflowRecord):
        name: str
        optional: str | None = None

    class Parent(WorkflowRecord):
        children: list[Child]

    data = record_data(Parent(children=[Child(name="a"), Child(name="b", optional="yes")]))

    assert data == {"children": [{"name": "a"}, {"name": "b", "optional": "yes"}]}


def test_yaml_argv_tool_input_data_uses_declared_fields() -> None:
    class Tool(YAMLArgvTool):
        argv_template = ("demo",)
        value: str
        optional: str | None = None

    assert record_data(Tool(value="x")) == {"value": "x"}


def test_workflow_tool_is_plain_structured_operation() -> None:
    class Tool(WorkflowTool):
        value: str

    assert record_data(Tool(value="x")) == {"value": "x"}


def test_argv_tool_renders_argv() -> None:
    class Tool(ArgvTool):
        argv_template = ("demo", "run")
        value: str

    assert Tool(value="x").argv() == ["demo", "run"]


def test_record_json_schema_includes_field_descriptions_and_nested_records() -> None:
    class Child(WorkflowRecord):
        name: str = Value("Child name", guidance="Use the canonical name.")

    class Parent(WorkflowRecord):
        child: Child = Value("Child object")
        tags: list[str] = Value("Tags", default_factory=list)

    schema = record_json_schema(Parent)

    assert schema["properties"]["child"]["properties"]["name"]["description"] == "Child name"
    assert schema["properties"]["child"]["properties"]["name"]["x-guidance"] == "Use the canonical name."
    assert schema["properties"]["tags"]["type"] == "array"
