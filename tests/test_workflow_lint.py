import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
COMMAND_LIB = REPO_ROOT / "capabilities" / "imperative-workflows" / "lib"
WORKFLOW_LINT = (
    REPO_ROOT
    / "capabilities"
    / "imperative-workflows"
    / "bin"
    / "imperative-workflows-lint"
)
sys.path.insert(0, str(COMMAND_LIB))

from workflow_lint import lint_file, lint_source  # noqa: E402


def test_lint_file_extracts_tagged_markdown_with_source_lines(tmp_path: Path) -> None:
    source = tmp_path / "agent.md"
    source.write_text(
        "---\nname: demo\n---\n\n# Demo\n\n"
        "```python agentic-workflow\n"
        "class Demo(AgentWorkflow):\n"
        "    def workflow(self) -> None:\n"
        "        self.do([\"create snapshot before commit\"])\n"
        "```\n",
        encoding="utf-8",
    )

    findings = lint_file(source)

    assert len(findings) == 1
    assert findings[0].code == "WF101"
    assert findings[0].line == 10


def test_lint_source_accepts_atomic_actions() -> None:
    findings = lint_source(
        """
class Demo:
    def workflow(self) -> None:
        self.do(["create branch-snapshot"])
        BranchSnapshot().run()
        flag: bool = self.evaluate("True when code changes exist.")
        if flag:
            count: int = self.evaluate("Number of unchecked TODO items.")
        else:
            delta: float = self.evaluate("Loss delta.")
        StatusTool().run()
        status: str = self.evaluate("Continuation status.")

class BranchSnapshot(YAMLArgvTool):
    argv_template: ClassVar[tuple[str, ...]] = ("branch-snapshot",)
    path: str = "snapshot"

class StatusTool(ArgvTool):
    argv_template: ClassVar[tuple[str, ...]] = ("git", "status", "--short")
    value: str = "status"
""",
        path="demo.py",
    )

    assert findings == []


def test_lint_source_accepts_adjacent_evaluations() -> None:
    findings = lint_source(
        """
class Demo:
    def workflow(self) -> None:
        requires_user: bool = self.evaluate("True when research continuation needs user input.")
        has_autonomous_work: bool = self.evaluate("True when actionable autonomous work remains.")
""",
        path="demo.py",
    )

    assert findings == []


def test_lint_source_accepts_conditional_boolean_evaluate() -> None:
    findings = lint_source(
        """
class Demo:
    def workflow(self) -> None:
        if self.evaluate("True when code changes exist."):
            self.do(["create branch-snapshot"])
        while not self.evaluate("True when no autonomous work remains."):
            self.do(["continue research loop"])
""",
        path="demo.py",
    )

    assert findings == []


def test_lint_source_rejects_conditional_evaluate_without_literal_subject() -> None:
    findings = lint_source(
        """
class Demo:
    def workflow(self, subject) -> None:
        if self.evaluate(subject):
            self.do(["create branch-snapshot"])
""",
        path="demo.py",
    )

    assert any(finding.code == "WF701" for finding in findings)


def test_lint_source_accepts_ask_user_in_user_facing_workflow() -> None:
    findings = lint_source(
        """
class Role(UserFacingWorkflow):
    def workflow(self) -> None:
        answer: str = self.ask_user("Ask the user for the missing research direction.")
        if self.evaluate("True when answer asks to stop."):
            self.do(["prepare final response"])
""",
        path="demo.py",
    )

    assert findings == []


def test_lint_source_rejects_ask_user_in_subagent_workflow() -> None:
    findings = lint_source(
        """
class Role(AgentWorkflow):
    def workflow(self) -> None:
        answer: str = self.ask_user("Ask the user for hidden subagent input.")
        self.do(["record subagent status"])
""",
        path="demo.py",
    )

    assert any(finding.code == "WF502" for finding in findings)


def test_lint_source_accepts_direct_list_and_literal_evaluations() -> None:
    findings = lint_source(
        '''
from typing import Literal

class Demo:
    def workflow(self) -> None:
        topics: list[str] = self.evaluate("List of relevant note topics.")
        status: Literal["available", "unavailable", "unknown"] = self.evaluate("Backend capacity status.")
''',
        path="demo.py",
    )

    assert findings == []


def test_lint_source_accepts_guidance_with_control_words() -> None:
    findings = lint_source(
        '''
from typing import Literal

class ExperimentLogAppend(YAMLArgvTool):
    argv_template: ClassVar[tuple[str, ...]] = ("experiment-log", "append")
    title: str = Value("Experiment log title.")

class Demo:
    def workflow(self) -> None:
        self.do(
            ["plan experiment"],
            guidance="If two variables change, then the result cannot identify the cause.",
        )
        status: Literal["available", "unavailable"] = self.evaluate(
            "Backend status.",
            guidance="Use unavailable when the backend command fails.",
        )
        request: ExperimentLogAppend = self.fill(
            ExperimentLogAppend,
            guidance="Include the final metric after verification.",
        )
        request.run()
''',
        path="demo.py",
    )

    assert findings == []


def test_lint_source_rejects_dynamic_guidance() -> None:
    findings = lint_source(
        """
class Demo:
    def workflow(self, text) -> None:
        self.do(["plan experiment"], guidance=text)
""",
        path="demo.py",
    )

    assert any(finding.code == "WF901" for finding in findings)


def test_lint_source_rejects_adjacent_do_statements() -> None:
    findings = lint_source(
        """
class Demo:
    def workflow(self) -> None:
        self.do(["read scoped experiment records"])
        self.do(["compare against baseline metric"])
""",
        path="demo.py",
    )

    assert any(finding.code == "WF601" for finding in findings)


def test_lint_source_rejects_control_flow_terms_in_action_strings() -> None:
    findings = lint_source(
        """
class Demo:
    def workflow(self) -> None:
        self.do(["create branch-snapshot before launching finalizer"])
        self.do(["if code changed, inspect branch-snapshot"])
""",
        path="demo.py",
    )

    assert [(finding.category, finding.term) for finding in findings if finding.code == "WF101"] == [
        ("ordering", "before"),
        ("conditions", "if"),
    ]


def test_lint_source_rejects_dynamic_do_actions() -> None:
    findings = lint_source(
        """
class Demo:
    def workflow(self, actions) -> None:
        self.do(actions)
""",
        path="demo.py",
    )

    assert len(findings) == 1
    assert findings[0].code == "WF001"


def test_lint_source_rejects_string_do_action() -> None:
    findings = lint_source(
        """
class Demo:
    def workflow(self) -> None:
        self.do("create branch-snapshot")
""",
        path="demo.py",
    )

    assert len(findings) == 1
    assert findings[0].code == "WF001"


def test_lint_source_rejects_unannotated_do_assignment() -> None:
    findings = lint_source(
        """
class Demo:
    def workflow(self) -> None:
        result = self.do(["analyze experiment result"])
""",
        path="demo.py",
    )

    assert len(findings) == 1
    assert findings[0].code == "WF201"


def test_lint_source_rejects_non_scalar_do_assignment() -> None:
    findings = lint_source(
        """
class Demo:
    def workflow(self) -> None:
        result: AnalysisResult = self.do(["analyze experiment result"])
""",
        path="demo.py",
    )

    assert [finding.code for finding in findings] == ["WF201"]


def test_lint_source_accepts_schema_evaluate_assignment() -> None:
    findings = lint_source(
        '''
from typing import Literal

class ResultAnalysis(WorkflowRecord):
    meaningful: bool = Value("True when metric evidence and verification output make the result durable.")
    status: Literal["meaningful", "trivial"] = Value("Status from metric evidence and verification output.")
    summary: str = Value("Compact evidence-grounded summary.")

class Demo:
    def workflow(self) -> None:
        result: ResultAnalysis = self.evaluate(ResultAnalysis)
''',
        path="demo.py",
    )

    assert findings == []


def test_lint_source_rejects_context_block() -> None:
    findings = lint_source(
        '''

class StartupFrontier(WorkflowRecord):
    next_research_step: str = Value("Next research step.")

class Demo(AgentWorkflow):
    def workflow(self) -> None:
        with self.context(backend_capacity_status="available"):
            frontier: StartupFrontier = self.evaluate(StartupFrontier)
''',
        path="demo.py",
    )

    assert any(finding.code == "WF501" for finding in findings)


def test_lint_source_rejects_evaluate_context_keyword() -> None:
    findings = lint_source(
        '''

class StartupFrontier(WorkflowRecord):
    next_research_step: str = Value("Next research step.")

class Demo:
    def workflow(self) -> None:
        frontier: StartupFrontier = self.evaluate(
            StartupFrontier,
            context=dict(backend_capacity_status="available"),
        )
''',
        path="demo.py",
    )

    assert any(finding.code == "WF702" for finding in findings)


def test_lint_source_accepts_grouped_actions() -> None:
    findings = lint_source(
        """
class Demo:
    def workflow(self) -> None:
        self.do(
            [
                "read scoped experiment records",
                "compare against baseline metric",
                "identify missing controls",
            ],
        )
""",
        path="demo.py",
    )

    assert findings == []


def test_lint_source_accepts_schema_list_fields() -> None:
    findings = lint_source(
        '''
from typing import List

class SnapshotRequest(WorkflowRecord):
    paths: list[str] = Value("List of explicit code snapshot paths.")
    checks: List[str] = Value("List of check commands.")

class Demo:
    def workflow(self) -> None:
        request: SnapshotRequest = self.evaluate(SnapshotRequest)
''',
        path="demo.py",
    )

    assert findings == []


def test_lint_source_rejects_dynamic_actions() -> None:
    findings = lint_source(
        """
class Demo:
    def workflow(self, items) -> None:
        self.do(items)
""",
        path="demo.py",
    )

    assert len(findings) == 1
    assert findings[0].code == "WF001"


def test_lint_source_rejects_legacy_work_items_keyword() -> None:
    findings = lint_source(
        """
class Demo:
    def workflow(self) -> None:
        self.do(["analyze results"], work_items=["read scoped experiment records"])
""",
        path="demo.py",
    )

    assert any(finding.code == "WF001" for finding in findings)


def test_lint_source_rejects_unknown_do_keyword() -> None:
    findings = lint_source(
        """
class Demo:
    def workflow(self) -> None:
        self.do(["inspect result"], finalizer_context="hidden context")
""",
        path="demo.py",
    )

    assert any(finding.code == "WF001" for finding in findings)


def test_lint_source_rejects_action_control_flow_terms() -> None:
    findings = lint_source(
        """
class Demo:
    def workflow(self) -> None:
        self.do([
            "read report before comparing metrics",
        ])
""",
        path="demo.py",
    )

    assert len(findings) == 1
    assert findings[0].code == "WF101"
    assert findings[0].term == "before"


def test_lint_source_accepts_local_schema_evaluate_assignment() -> None:
    findings = lint_source(
        '''

class Demo:
    def workflow(self) -> None:
        class StartupReadingPlan(WorkflowRecord):
            relevant_note_topics: list[str] = Value("Relevant note topics.")

        startup: StartupReadingPlan = self.evaluate(StartupReadingPlan)
''',
        path="demo.py",
    )

    assert findings == []


def test_lint_source_accepts_local_schema_evaluation() -> None:
    findings = lint_source(
        '''

class Demo:
    def workflow(self) -> None:
        class ResultAnalysis(WorkflowRecord):
            summary: str = Value("Result analysis summary.")

        analysis: ResultAnalysis = self.evaluate(ResultAnalysis)
''',
        path="demo.py",
    )

    assert findings == []


def test_lint_source_accepts_local_schema_fill_assignment() -> None:
    findings = lint_source(
        '''

class Demo:
    def workflow(self) -> None:
        class ExperimentLogAppend(YAMLArgvTool):
            argv_template: ClassVar[tuple[str, ...]] = ("experiment-log", "append")
            title: str = Value("Experiment log title.")

        experiment_log: ExperimentLogAppend = self.fill(ExperimentLogAppend)
        experiment_log.launch_detached()
''',
        path="demo.py",
    )

    assert findings == []


def test_lint_source_rejects_local_schema_not_adjacent_to_evaluate() -> None:
    findings = lint_source(
        '''

class Demo:
    def workflow(self) -> None:
        class StartupReadingPlan(WorkflowRecord):
            relevant_note_topics: list[str] = Value("Relevant note topics.")

        self.do(["inspect status"])
        startup: StartupReadingPlan = self.evaluate(StartupReadingPlan)
''',
        path="demo.py",
    )

    assert any(finding.code == "WF703" for finding in findings)


def test_lint_source_rejects_empty_actions_for_assigned_do() -> None:
    findings = lint_source(
        '''

class Demo:
    def workflow(self) -> None:
        class StartupReadingPlan(WorkflowRecord):
            relevant_note_topics: list[str] = Value("Relevant note topics.")

        startup: StartupReadingPlan = self.do([])
''',
        path="demo.py",
    )

    assert any(finding.code == "WF001" for finding in findings)
    assert any(finding.code == "WF201" for finding in findings)


def test_lint_source_rejects_unannotated_evaluate_assignment() -> None:
    findings = lint_source(
        '''

class StartupReadingPlan(WorkflowRecord):
    relevant_note_topics: list[str] = Value("Relevant note topics.")

class Demo:
    def workflow(self) -> None:
        startup = self.evaluate(StartupReadingPlan)
''',
        path="demo.py",
    )

    assert len(findings) == 1
    assert findings[0].code == "WF701"


def test_lint_source_rejects_mismatched_evaluate_annotation() -> None:
    findings = lint_source(
        '''

class StartupReadingPlan(WorkflowRecord):
    relevant_note_topics: list[str] = Value("Relevant note topics.")

class OtherPlan(WorkflowRecord):
    relevant_note_topics: list[str] = Value("Relevant note topics.")

class Demo:
    def workflow(self) -> None:
        startup: OtherPlan = self.evaluate(StartupReadingPlan)
''',
        path="demo.py",
    )

    assert len(findings) == 1
    assert findings[0].code == "WF701"


def test_lint_source_rejects_loose_evaluate_context_keyword() -> None:
    findings = lint_source(
        '''
from typing import Literal

class StartupFrontier(WorkflowRecord):
    backend_capacity_status: Literal["available", "unavailable", "unknown"] = Value("Backend capacity status.")
    next_research_step: str = Value("Next research step.")

class Demo:
    def workflow(self) -> None:
        backend_capacity_status = "available"
        frontier: StartupFrontier = self.evaluate(
            StartupFrontier,
            backend_capacity_status=backend_capacity_status,
        )
''',
        path="demo.py",
    )

    assert any(finding.code == "WF702" for finding in findings)


def test_lint_source_rejects_duplicate_evaluate_subject() -> None:
    findings = lint_source(
        '''

class StartupReadingPlan(WorkflowRecord):
    relevant_note_topics: list[str] = Value("Relevant note topics.")

class Demo:
    def workflow(self) -> None:
        startup: StartupReadingPlan = self.evaluate(StartupReadingPlan, subject=StartupReadingPlan)
''',
        path="demo.py",
    )

    assert any(finding.code == "WF702" for finding in findings)


def test_lint_source_rejects_evaluate_with_non_schema() -> None:
    findings = lint_source(
        """
class Demo:
    def workflow(self) -> None:
        value: str = self.evaluate(str)
""",
        path="demo.py",
    )

    assert len(findings) == 1
    assert findings[0].code == "WF701"


def test_lint_source_rejects_empty_actions_for_side_effect_do() -> None:
    findings = lint_source(
        """
class Demo:
    def workflow(self) -> None:
        self.do([])
""",
        path="demo.py",
    )

    assert len(findings) == 1
    assert findings[0].code == "WF001"


def test_lint_source_rejects_empty_actions_for_assigned_scalar_do() -> None:
    findings = lint_source(
        """
class Demo:
    def workflow(self) -> None:
        value: str = self.do([])
""",
        path="demo.py",
    )

    assert any(finding.code == "WF001" for finding in findings)
    assert any(finding.code == "WF201" for finding in findings)


def test_lint_source_rejects_schema_evaluate_assignment_without_value_descriptions() -> None:
    findings = lint_source(
        '''
from typing import Literal

class ResultAnalysis(WorkflowRecord):
    status: Literal["meaningful", "trivial"]
    summary: str

class Demo:
    def workflow(self) -> None:
        result: ResultAnalysis = self.evaluate(ResultAnalysis)
''',
        path="demo.py",
    )

    assert len(findings) == 1
    assert findings[0].code == "WF701"


def test_lint_source_rejects_schema_field_with_dict_type() -> None:
    findings = lint_source(
        '''

class ResultAnalysis(WorkflowRecord):
    opaque_data: dict[str, str] = Value("Opaque data.")

class Demo:
    def workflow(self) -> None:
        result: ResultAnalysis = self.evaluate(ResultAnalysis)
''',
        path="demo.py",
    )

    assert len(findings) == 1
    assert findings[0].code == "WF701"


def test_lint_source_rejects_returned_do_value() -> None:
    findings = lint_source(
        """
class Demo:
    def workflow(self) -> None:
        return self.do(["write experiment summary"])
""",
        path="demo.py",
    )

    assert len(findings) == 1
    assert findings[0].code == "WF201"


def test_lint_source_allows_explicit_line_suppression() -> None:
    findings = lint_source(
        """
class Demo:
    def workflow(self) -> None:
        self.do(["compute first-order approximation"])  # workflow-lint: allow=first
""",
        path="demo.py",
    )

    assert findings == []


def test_workflow_lint_cli_reports_findings(tmp_path: Path) -> None:
    workflow = tmp_path / "workflow.py"
    workflow.write_text(
        """
class Demo:
    def workflow(self) -> None:
        self.do(["try note-updater unless no lesson exists"])
""",
        encoding="utf-8",
    )

    result = subprocess.run(
        [str(WORKFLOW_LINT), str(workflow)],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 1
    assert "WF101" in result.stderr
    assert "try" in result.stderr


def test_lint_source_rejects_missing_return_annotations() -> None:
    findings = lint_source(
        """
class Demo:
    def workflow(self):
        self.do(["create branch-snapshot"])
""",
        path="demo.py",
    )

    assert any(finding.code == "WF301" for finding in findings)


def test_lint_source_rejects_workflow_without_call_entrypoint() -> None:
    findings = lint_source(
        """
class Role(AgentWorkflow):
    def review(self) -> None:
        self.do(["inspect review scope"])
""",
        path="demo.py",
    )

    assert any(finding.code == "WF401" for finding in findings)


def test_lint_source_accepts_workflow_entrypoint() -> None:
    findings = lint_source(
        """
class Role(AgentWorkflow):
    def workflow(self) -> None:
        self.do(["inspect review scope"])
""",
        path="demo.py",
    )

    assert findings == []


def test_lint_source_accepts_declared_workflow_helper_method() -> None:
    findings = lint_source(
        """
class Role(AgentWorkflow):
    def on_startup(self) -> None:
        self.read_state()

    def read_state(self) -> None:
        self.do(["read work-state records"])

    def workflow(self) -> None:
        self.do(["continue research"])
""",
        path="demo.py",
    )

    assert findings == []


def test_lint_source_accepts_constructor_configured_workflow() -> None:
    findings = lint_source(
        """

class ReviewRequest(WorkflowRecord):
    path: str

class ReviewResult(WorkflowRecord):
    summary: str

class Role(AgentWorkflow):
    request: ReviewRequest
    retry_count: int = 0

    def workflow(self) -> ReviewResult:
        self.do(["inspect review scope"])
        return ReviewResult(summary="ok")
""",
        path="demo.py",
    )

    assert findings == []


def test_lint_source_accepts_subagent_and_tool_invocation_methods() -> None:
    findings = lint_source(
        """
from typing import ClassVar

class OtherRole(AgentWorkflow):
    def workflow(self) -> None:
        self.do(["inspect review scope"])

class ToolRequest(YAMLArgvTool):
    argv_template: ClassVar[tuple[str, ...]] = ("demo-tool",)
    value: str

class Role(AgentWorkflow):
    def workflow(self) -> None:
        OtherRole().run()
        other_job: Job[None] = OtherRole().launch()
        ToolRequest(value="x").run()
        ToolRequest(value="x").launch_detached()
""",
        path="demo.py",
    )

    assert findings == []


def test_lint_source_accepts_workflow_tool_as_evaluate_schema() -> None:
    findings = lint_source(
        """
from typing import ClassVar

class ExperimentLogAppend(WorkflowTool):
    title: str = Value("Experiment log title")

class Role(AgentWorkflow):
    def workflow(self) -> None:
        experiment_log: ExperimentLogAppend = self.fill(ExperimentLogAppend)
        experiment_log.launch_detached()
""",
        path="demo.py",
    )

    assert findings == []


def test_lint_source_rejects_bare_tracked_launch() -> None:
    findings = lint_source(
        """
class Role(AgentWorkflow):
    def workflow(self) -> None:
        OtherRole().launch()
""",
        path="demo.py",
    )

    assert [finding.code for finding in findings] == ["WF802"]


def test_lint_source_rejects_unannotated_tracked_launch() -> None:
    findings = lint_source(
        """
class Role(AgentWorkflow):
    def workflow(self) -> None:
        job = OtherRole().launch()
""",
        path="demo.py",
    )

    assert [finding.code for finding in findings] == ["WF802"]


def test_lint_source_rejects_assigned_detached_launch() -> None:
    findings = lint_source(
        """
class Role(AgentWorkflow):
    def workflow(self) -> None:
        job: Job[None] = OtherRole().launch_detached()
""",
        path="demo.py",
    )

    assert [finding.code for finding in findings] == ["WF802"]


def test_lint_source_rejects_constructor_config_dict_field() -> None:
    findings = lint_source(
        """
class Role(AgentWorkflow):
    request: dict[str, str]

    def workflow(self) -> None:
        self.do(["inspect review scope"])
""",
        path="demo.py",
    )

    assert any(finding.code == "WF406" for finding in findings)


def test_lint_source_rejects_string_tool_invocation() -> None:
    findings = lint_source(
        """
class Role(AgentWorkflow):
    def workflow(self) -> None:
        self.run_tool("branch-snapshot")
""",
        path="demo.py",
    )

    assert any(finding.code == "WF501" for finding in findings)


def test_lint_source_rejects_tool_invocation_kwargs() -> None:
    findings = lint_source(
        """
class BranchSnapshot(YAMLArgvTool):
    argv_template: ClassVar[tuple[str, ...]] = ("branch-snapshot",)
    path: str

class Role(AgentWorkflow):
    def workflow(self) -> None:
        self.run_tool(BranchSnapshot(path="snapshot"), timeout_seconds=30)
""",
        path="demo.py",
    )

    assert any(finding.code == "WF501" for finding in findings)


def test_lint_source_rejects_subagent_invocation_kwargs() -> None:
    findings = lint_source(
        """
class OtherRole(AgentWorkflow):
    def workflow(self) -> None:
        self.do(["inspect review scope"])

class Role(AgentWorkflow):
    def workflow(self) -> None:
        self.start_subagent(OtherRole(), fork_context=False)
""",
        path="demo.py",
    )

    assert any(finding.code == "WF501" for finding in findings)


def test_lint_source_rejects_workflow_call_keyword_only_parameters() -> None:
    findings = lint_source(
        """
class Role(AgentWorkflow):
    def workflow(self, *, request: str) -> None:
        self.do(["inspect review scope"])
""",
        path="demo.py",
    )

    assert any(finding.code == "WF402" for finding in findings)


def test_lint_source_rejects_workflow_call_kwargs() -> None:
    findings = lint_source(
        """
class Role(AgentWorkflow):
    def workflow(self, **kwargs) -> None:
        self.do(["inspect review scope"])
""",
        path="demo.py",
    )

    assert any(finding.code == "WF402" for finding in findings)


def test_lint_source_rejects_untyped_workflow_call_parameter() -> None:
    findings = lint_source(
        """
class Role(AgentWorkflow):
    def workflow(self, request) -> None:
        self.do(["inspect review scope"])
""",
        path="demo.py",
    )

    assert any(finding.code == "WF403" for finding in findings)


def test_lint_source_rejects_workflow_call_dict_parameter() -> None:
    findings = lint_source(
        """
class Role(AgentWorkflow):
    def workflow(self, request: dict[str, str]) -> None:
        self.do(["inspect review scope"])
""",
        path="demo.py",
    )

    assert any(finding.code == "WF404" for finding in findings)


def test_lint_source_rejects_workflow_call_any_parameter() -> None:
    findings = lint_source(
        """
from typing import Any

class Role(AgentWorkflow):
    def workflow(self, request: Any) -> None:
        self.do(["inspect review scope"])
""",
        path="demo.py",
    )

    assert any(finding.code == "WF404" for finding in findings)


def test_lint_source_rejects_workflow_call_dict_return() -> None:
    findings = lint_source(
        """
class Role(AgentWorkflow):
    def workflow(self) -> dict[str, str]:
        self.do(["inspect review scope"])
        return {"status": "ok"}
""",
        path="demo.py",
    )

    assert any(finding.code == "WF405" for finding in findings)


def test_lint_source_rejects_workflow_call_any_return() -> None:
    findings = lint_source(
        """
from typing import Any

class Role(AgentWorkflow):
    def workflow(self) -> Any:
        self.do(["inspect review scope"])
        return None
""",
        path="demo.py",
    )

    assert any(finding.code == "WF405" for finding in findings)


def test_lint_source_rejects_context_packet_field() -> None:
    findings = lint_source(
        """
class Role(AgentWorkflow):
    def workflow(self) -> None:
        class FinalizerRequest(WorkflowRecord):
            context_packet: str
""",
        path="demo.py",
    )

    assert any(finding.code == "WF801" for finding in findings)


def test_lint_source_rejects_undeclared_self_method_calls() -> None:
    findings = lint_source(
        """
class Role(AgentWorkflow):
    def workflow(self) -> None:
        await self.launch_workflow(OtherRole)
""",
        path="demo.py",
    )

    assert any(finding.code == "WF501" for finding in findings)
