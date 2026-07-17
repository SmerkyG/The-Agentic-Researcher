from __future__ import annotations

from pathlib import Path
import sys
from typing import ClassVar, Literal

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
PACKAGE_ROOT = REPO_ROOT / "capabilities" / "imperative-workflows" / "package"
sys.path.insert(0, str(PACKAGE_ROOT))

from agentic_workflows.contract import Value, WorkflowRecord  # noqa: E402
from agentic_workflows.fill_spec import (  # noqa: E402
    AgentRequestSpec,
    AgentRequestSpecBuilder,
    FillSpecError,
    GuidanceScope,
    Observe,
    agent_request_spec,
    assignment_schema,
    decode_assignments,
    field,
    guidance,
    observe,
    output_schema,
    render_agent_request,
    step,
    var,
)


class ExampleRequest(WorkflowRecord):
    dispatch_metadata: ClassVar[str] = "hidden"
    required: str = Value("Required request value")
    optional: str = "default"


class FirstChoice(WorkflowRecord):
    first: str = Value("First choice value")


class SecondChoice(WorkflowRecord):
    second: str = Value("Second choice value")


def example_spec() -> AgentRequestSpec:
    with agent_request_spec("iteration") as declaration:
        observe(tool_result={"returncode": 0, "stdout": "measured"})
        with guidance("Use the full-decision scale before concluding."):
            var("hypothesis", str, "Testable hypothesis")
            step("Run the planned experiment.")
            var("evidence", list[str], "Concrete measured evidence")
        field(
            "summary",
            str,
            "Conclusion supported by `evidence`",
            guidance="Do not substitute expected results.",
        )
        field(
            "capacity",
            Literal["available", "unavailable", "unknown"],
            "Remote capacity classification",
        )

    return declaration.spec


def test_renderer_preserves_node_order_and_trailing_guidance_scope() -> None:
    rendered = render_agent_request(example_spec())

    assert "Process agent request `iteration`:" in rendered
    assert rendered.index("Observe external results") < rendered.index("Testable hypothesis")
    assert rendered.index("Testable hypothesis") < rendered.index("Run the planned experiment.")
    assert rendered.index("Run the planned experiment.") < rendered.index("Concrete measured evidence")
    assert rendered.index("Concrete measured evidence") < rendered.index(
        "Use the full-decision scale before concluding."
    )
    assert rendered.index("Use the full-decision scale before concluding.") < rendered.index(
        "Conclusion supported by `evidence`"
    )
    assert rendered.endswith(
        "exactly these assignments: hypothesis, evidence, summary, capacity.\n"
    )


def test_assignment_schema_includes_vars_but_output_schema_contains_only_fields() -> None:
    spec = example_spec()
    all_assignments = assignment_schema(spec)
    returned = output_schema(spec)

    assert list(all_assignments["properties"]) == [
        "hypothesis",
        "evidence",
        "summary",
        "capacity",
    ]
    assert list(returned["properties"]) == ["summary", "capacity"]
    assert returned["properties"]["capacity"]["enum"] == [
        "available",
        "unavailable",
        "unknown",
    ]


def test_named_workflow_record_schema_respects_defaults() -> None:
    with agent_request_spec("request_fill") as declaration:
        field("request", ExampleRequest)

    request = output_schema(declaration.spec)["properties"]["request"]
    assert request["required"] == ["required"]
    assert request["properties"]["required"]["description"] == "Required request value"
    assert request["properties"]["optional"]["default"] == "default"
    assert "dispatch_metadata" not in request["properties"]


def test_decode_assignments_validates_all_values_and_returns_only_fields() -> None:
    variables, returned = decode_assignments(
        example_spec(),
        {
            "hypothesis": "measured hypothesis",
            "evidence": ["1.2 ms"],
            "summary": "faster",
            "capacity": "available",
        },
    )

    assert variables == {"hypothesis": "measured hypothesis", "evidence": ["1.2 ms"]}
    assert returned == {"summary": "faster", "capacity": "available"}

    with pytest.raises(FillSpecError, match="missing assignments"):
        decode_assignments(example_spec(), {"summary": "incomplete"})


def test_union_record_decoding_selects_shape_by_declared_fields() -> None:
    with agent_request_spec() as declaration:
        field("choice", FirstChoice | SecondChoice)

    _variables, returned = decode_assignments(
        declaration.spec,
        {"choice": {"second": "selected"}},
    )

    assert returned == {"choice": SecondChoice(second="selected")}


def test_identifiers_are_unique_across_guidance_scopes() -> None:
    with pytest.raises(FillSpecError, match="duplicate agent-request identifiers"):
        with agent_request_spec():
            var("answer", str, "first")
            with guidance("Nested qualification"):
                field("answer", str, "second")


def test_observe_and_guidance_validate_their_contents() -> None:
    with pytest.raises(FillSpecError, match="named external value"):
        Observe()

    with pytest.raises(FillSpecError, match="at least one enclosed"):
        GuidanceScope(guidance="empty")


def test_declarative_statements_require_an_active_block() -> None:
    with pytest.raises(FillSpecError, match="active agent_request"):
        field("result", str)
    with pytest.raises(FillSpecError, match="active agent_request"):
        var("result", str)
    with pytest.raises(FillSpecError, match="active agent_request"):
        step("Do work.")
    with pytest.raises(FillSpecError, match="active agent request"):
        with guidance("Stay focused."):
            step("Do work.")


def test_failed_block_is_not_compiled_and_does_not_leak_context() -> None:
    declaration = agent_request_spec("failed")
    with pytest.raises(RuntimeError, match="construction failed"):
        with declaration:
            field("result", str)
            raise RuntimeError("construction failed")

    with pytest.raises(FillSpecError, match="unavailable"):
        declaration.spec

    with agent_request_spec("next_fill") as next_declaration:
        field("result", str)
    assert next_declaration.spec.name == "next_fill"


def test_root_request_cannot_be_nested() -> None:
    with agent_request_spec("outer"):
        field("result", str)
        with pytest.raises(FillSpecError, match="cannot be nested"):
            with agent_request_spec("inner"):
                field("other", str)


def test_builder_callback_populates_deferred_field_attributes() -> None:
    def resolve(_spec: AgentRequestSpec) -> dict[str, object]:
        return {"answer": "resolved"}

    declaration = AgentRequestSpecBuilder(on_complete=resolve)
    with declaration as result:
        field("answer", str)
        with pytest.raises(FillSpecError, match="before successful block exit"):
            _ = result.answer

    assert result.answer == "resolved"
