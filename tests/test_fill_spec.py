from __future__ import annotations

from pathlib import Path
import sys
from typing import ClassVar, Literal

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
PACKAGE_ROOT = REPO_ROOT / "capabilities" / "imperative-workflows" / "package"
sys.path.insert(0, str(REPO_ROOT / "scripts" / "package"))
sys.path.insert(0, str(PACKAGE_ROOT))

from agentic_workflows.contract import Value, WorkflowRecord  # noqa: E402
from agentic_workflows.request_spec import (  # noqa: E402
    AgentRequest,
    AgentObservation,
    AgentRequestSpec,
    FillSpecError,
    GuidanceScope,
    assignment_schema,
    decode_assignments,
    guidance,
    local,
    output_schema,
    render_agent_request,
    result,
    step,
)


class ExampleRequest(WorkflowRecord):
    dispatch_metadata: ClassVar[str] = "hidden"
    required: str = Value("Required request value")
    optional: str = "default"


class FirstChoice(WorkflowRecord):
    first: str = Value("First choice value")


class SecondChoice(WorkflowRecord):
    second: str = Value("Second choice value")


class ExampleAgentRequest(AgentRequest):
    with guidance("Use the full-decision scale before concluding."):
        hypothesis: str = local("Testable hypothesis")
        evidence: list[str] = local(f"Concrete evidence for {hypothesis}")
        step(f"Run the experiment for {hypothesis}.")
    summary: str = result(
        f"Conclusion supported by {evidence}",
        guidance="Do not substitute expected results.",
    )
    capacity: Literal["available", "unavailable", "unknown"] = result(
        "Remote capacity classification"
    )


def test_class_request_preserves_order_and_backticked_references() -> None:
    rendered = render_agent_request(ExampleAgentRequest.__request_spec__)

    assert "Process agent request `ExampleAgentRequest`:" in rendered
    assert "Concrete evidence for `hypothesis`" in rendered
    assert "Run the experiment for `hypothesis`." in rendered
    assert "Conclusion supported by `evidence`" in rendered
    assert rendered.index("Testable hypothesis") < rendered.index(
        "Concrete evidence for `hypothesis`"
    )
    assert rendered.index("Concrete evidence for `hypothesis`") < rendered.index(
        "Use the full-decision scale before concluding."
    )
    assert rendered.endswith(
        "exactly these assignments: hypothesis, evidence, summary, capacity.\n"
    )


def test_existing_python_values_interpolate_concretely() -> None:
    state_dir = "/tmp/research-state"

    class ConcreteInput(AgentRequest):
        step(f"Read the report from {state_dir}.")
        summary: str = result("summary")

    rendered = render_agent_request(ConcreteInput.__request_spec__)

    assert "Read the report from /tmp/research-state." in rendered
    assert "`state_dir`" not in rendered


def test_assignment_schema_includes_locals_but_output_contains_only_results() -> None:
    spec = ExampleAgentRequest.__request_spec__
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


def test_queued_observations_render_before_declared_nodes() -> None:
    declared = ExampleAgentRequest.__request_spec__
    spec = AgentRequestSpec(
        declared.items,
        name=declared.name,
        observations=(
            AgentObservation(
                {"returncode": 0, "stdout": "measured"},
                desc="Focused verification command result.",
            ),
        ),
    )

    rendered = render_agent_request(spec)

    assert "External observations queued for this request:" in rendered
    assert "Observation 1 (dict) — Focused verification command result." in rendered
    assert rendered.index("External observations") < rendered.index(
        "Testable hypothesis"
    )


def test_named_workflow_record_schema_respects_defaults() -> None:
    class RequestFill(AgentRequest):
        request: ExampleRequest = result("request")

    request = output_schema(RequestFill.__request_spec__)["properties"]["request"]
    assert request["required"] == ["required"]
    assert request["properties"]["required"]["description"] == "Required request value"
    assert request["properties"]["optional"]["default"] == "default"
    assert "dispatch_metadata" not in request["properties"]


def test_decode_assignments_validates_values_and_returns_only_results() -> None:
    variables, returned = decode_assignments(
        ExampleAgentRequest.__request_spec__,
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
        decode_assignments(ExampleAgentRequest.__request_spec__, {"summary": "incomplete"})


def test_union_record_decoding_selects_shape_by_declared_fields() -> None:
    class ChoiceRequest(AgentRequest):
        choice: FirstChoice | SecondChoice = result("choice")

    _variables, returned = decode_assignments(
        ChoiceRequest.__request_spec__,
        {"choice": {"second": "selected"}},
    )

    assert returned == {"choice": SecondChoice(second="selected")}


def test_class_request_rejects_unannotated_plain_and_duplicate_assignments() -> None:
    with pytest.raises(FillSpecError, match="requires an explicit annotation"):

        class MissingAnnotation(AgentRequest):
            answer = result("answer")

    with pytest.raises(FillSpecError, match="may contain only declarations"):

        class PlainAssignment(AgentRequest):
            answer: str = result("answer")
            extra = "not a declaration"

    with pytest.raises(FillSpecError, match="duplicate agent-request identifier"):

        class DuplicateAssignment(AgentRequest):
            answer: str = local("first")
            answer: str = result("second")


def test_declarations_require_agent_request_class_body() -> None:
    with pytest.raises(FillSpecError, match="AgentRequest class body"):
        local("answer")
    with pytest.raises(FillSpecError, match="AgentRequest class body"):
        result("answer")
    with pytest.raises(FillSpecError, match="AgentRequest class body"):
        step("Do work.")
    with pytest.raises(FillSpecError, match="AgentRequest class body"):
        with guidance("Stay focused."):
            pass


def test_guidance_validates_contents() -> None:
    with pytest.raises(FillSpecError, match="observation description"):
        AgentObservation("value", desc="")

    with pytest.raises(FillSpecError, match="at least one enclosed"):
        GuidanceScope(guidance="empty")


def test_f_string_format_specifier_is_rejected() -> None:
    with pytest.raises(FillSpecError, match="format specifiers"):

        class InvalidFormat(AgentRequest):
            value: float = local("value")
            summary: str = result(f"summary {value:.2f}")
