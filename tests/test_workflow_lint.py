import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
COMMAND_LIB = REPO_ROOT / "scripts" / "lib" / "commands"
WORKFLOW_LINT = REPO_ROOT / "scripts" / "bin" / "workflow-lint"
sys.path.insert(0, str(COMMAND_LIB))

from workflow_lint import lint_source  # noqa: E402


def test_lint_source_accepts_atomic_actions() -> None:
    findings = lint_source(
        """
class Demo:
    def run(self) -> None:
        self.do(["create branch-snapshot"])
        self.run_tool("branch-snapshot")
        flag: bool = self.evaluate("True when code changes exist.")
        if flag:
            count: int = self.evaluate("Number of unchecked TODO items.")
        else:
            delta: float = self.evaluate("Loss delta.")
        self.run_tool("status")
        status: str = self.evaluate("Continuation status.")
""",
        path="demo.py",
    )

    assert findings == []


def test_lint_source_accepts_adjacent_evaluations() -> None:
    findings = lint_source(
        """
class Demo:
    def run(self) -> None:
        requires_user: bool = self.evaluate("True when research continuation needs user input.")
        has_autonomous_work: bool = self.evaluate("True when actionable autonomous work remains.")
""",
        path="demo.py",
    )

    assert findings == []


def test_lint_source_accepts_direct_list_and_literal_evaluations() -> None:
    findings = lint_source(
        '''
from typing import Literal

class Demo:
    def run(self) -> None:
        topics: list[str] = self.evaluate("List of relevant note topics.")
        status: Literal["available", "unavailable", "unknown"] = self.evaluate("Backend capacity status.")
''',
        path="demo.py",
    )

    assert findings == []


def test_lint_source_rejects_adjacent_do_statements() -> None:
    findings = lint_source(
        """
class Demo:
    def run(self) -> None:
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
    def run(self) -> None:
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
    def run(self, actions) -> None:
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
    def run(self) -> None:
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
    def run(self) -> None:
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
    def run(self) -> None:
        result: AnalysisResult = self.do(["analyze experiment result"])
""",
        path="demo.py",
    )

    assert [finding.code for finding in findings] == ["WF201"]


def test_lint_source_accepts_schema_evaluate_assignment() -> None:
    findings = lint_source(
        '''
from dataclasses import dataclass
from typing import Literal

@dataclass
class ResultAnalysis:
    meaningful: bool = Value("True when metric evidence and verification output make the result durable.")
    status: Literal["meaningful", "trivial"] = Value("Status from metric evidence and verification output.")
    summary: str = Value("Compact evidence-grounded summary.")

class Demo:
    def run(self) -> None:
        result: ResultAnalysis = self.evaluate(ResultAnalysis)
''',
        path="demo.py",
    )

    assert findings == []


def test_lint_source_accepts_context_block() -> None:
    findings = lint_source(
        '''
from dataclasses import dataclass

@dataclass
class StartupFrontier:
    next_research_step: str = Value("Next research step.")

class Demo:
    def run(self) -> None:
        with self.context(backend_capacity_status="available"):
            frontier: StartupFrontier = self.evaluate(StartupFrontier)
''',
        path="demo.py",
    )

    assert findings == []


def test_lint_source_rejects_evaluate_context_keyword() -> None:
    findings = lint_source(
        '''
from dataclasses import dataclass

@dataclass
class StartupFrontier:
    next_research_step: str = Value("Next research step.")

class Demo:
    def run(self) -> None:
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
    def run(self) -> None:
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
from dataclasses import dataclass
from typing import List

@dataclass
class SnapshotRequest:
    paths: list[str] = Value("List of explicit code snapshot paths.")
    checks: List[str] = Value("List of check commands.")

class Demo:
    def run(self) -> None:
        request: SnapshotRequest = self.evaluate(SnapshotRequest)
''',
        path="demo.py",
    )

    assert findings == []


def test_lint_source_rejects_dynamic_actions() -> None:
    findings = lint_source(
        """
class Demo:
    def run(self, items) -> None:
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
    def run(self) -> None:
        self.do(["analyze results"], work_items=["read scoped experiment records"])
""",
        path="demo.py",
    )

    assert any(finding.code == "WF001" for finding in findings)


def test_lint_source_rejects_action_control_flow_terms() -> None:
    findings = lint_source(
        """
class Demo:
    def run(self) -> None:
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
from dataclasses import dataclass

class Demo:
    def run(self) -> None:
        @dataclass
        class StartupReadingPlan:
            relevant_note_topics: list[str] = Value("Relevant note topics.")

        startup: StartupReadingPlan = self.evaluate(StartupReadingPlan)
''',
        path="demo.py",
    )

    assert findings == []


def test_lint_source_accepts_local_schema_evaluation() -> None:
    findings = lint_source(
        '''
from dataclasses import dataclass

class Demo:
    def run(self) -> None:
        @dataclass
        class ResultAnalysis:
            summary: str = Value("Result analysis summary.")

        analysis: ResultAnalysis = self.evaluate(ResultAnalysis)
''',
        path="demo.py",
    )

    assert findings == []


def test_lint_source_rejects_local_schema_not_adjacent_to_evaluate() -> None:
    findings = lint_source(
        '''
from dataclasses import dataclass

class Demo:
    def run(self) -> None:
        @dataclass
        class StartupReadingPlan:
            relevant_note_topics: list[str] = Value("Relevant note topics.")

        self.run_tool("status")
        startup: StartupReadingPlan = self.evaluate(StartupReadingPlan)
''',
        path="demo.py",
    )

    assert any(finding.code == "WF703" for finding in findings)


def test_lint_source_rejects_empty_actions_for_assigned_do() -> None:
    findings = lint_source(
        '''
from dataclasses import dataclass

class Demo:
    def run(self) -> None:
        @dataclass
        class StartupReadingPlan:
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
from dataclasses import dataclass

@dataclass
class StartupReadingPlan:
    relevant_note_topics: list[str] = Value("Relevant note topics.")

class Demo:
    def run(self) -> None:
        startup = self.evaluate(StartupReadingPlan)
''',
        path="demo.py",
    )

    assert len(findings) == 1
    assert findings[0].code == "WF701"


def test_lint_source_rejects_mismatched_evaluate_annotation() -> None:
    findings = lint_source(
        '''
from dataclasses import dataclass

@dataclass
class StartupReadingPlan:
    relevant_note_topics: list[str] = Value("Relevant note topics.")

@dataclass
class OtherPlan:
    relevant_note_topics: list[str] = Value("Relevant note topics.")

class Demo:
    def run(self) -> None:
        startup: OtherPlan = self.evaluate(StartupReadingPlan)
''',
        path="demo.py",
    )

    assert len(findings) == 1
    assert findings[0].code == "WF701"


def test_lint_source_rejects_loose_evaluate_context_keyword() -> None:
    findings = lint_source(
        '''
from dataclasses import dataclass
from typing import Literal

@dataclass
class StartupFrontier:
    backend_capacity_status: Literal["available", "unavailable", "unknown"] = Value("Backend capacity status.")
    next_research_step: str = Value("Next research step.")

class Demo:
    def run(self) -> None:
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
from dataclasses import dataclass

@dataclass
class StartupReadingPlan:
    relevant_note_topics: list[str] = Value("Relevant note topics.")

class Demo:
    def run(self) -> None:
        startup: StartupReadingPlan = self.evaluate(StartupReadingPlan, subject=StartupReadingPlan)
''',
        path="demo.py",
    )

    assert any(finding.code == "WF702" for finding in findings)


def test_lint_source_rejects_evaluate_with_non_schema() -> None:
    findings = lint_source(
        """
class Demo:
    def run(self) -> None:
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
    def run(self) -> None:
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
    def run(self) -> None:
        value: str = self.do([])
""",
        path="demo.py",
    )

    assert any(finding.code == "WF001" for finding in findings)
    assert any(finding.code == "WF201" for finding in findings)


def test_lint_source_rejects_schema_evaluate_assignment_without_value_descriptions() -> None:
    findings = lint_source(
        '''
from dataclasses import dataclass
from typing import Literal

@dataclass
class ResultAnalysis:
    status: Literal["meaningful", "trivial"]
    summary: str

class Demo:
    def run(self) -> None:
        result: ResultAnalysis = self.evaluate(ResultAnalysis)
''',
        path="demo.py",
    )

    assert len(findings) == 1
    assert findings[0].code == "WF701"


def test_lint_source_rejects_schema_field_with_dict_type() -> None:
    findings = lint_source(
        '''
from dataclasses import dataclass

@dataclass
class ResultAnalysis:
    payload: dict[str, str] = Value("Opaque payload.")

class Demo:
    def run(self) -> None:
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
    def run(self) -> None:
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
    def run(self) -> None:
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
    def run(self) -> None:
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
    def run(self):
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


def test_lint_source_accepts_workflow_with_call_entrypoint() -> None:
    findings = lint_source(
        """
class Role(AgentWorkflow):
    async def __call__(self) -> None:
        self.do(["inspect review scope"])
""",
        path="demo.py",
    )

    assert findings == []


def test_lint_source_accepts_workflow_call_with_typed_parameters() -> None:
    findings = lint_source(
        """
from dataclasses import dataclass

@dataclass
class ReviewRequest:
    path: str

@dataclass
class ReviewResult:
    summary: str

class Role(AgentWorkflow):
    async def __call__(self, request: ReviewRequest, retry_count: int = 0) -> ReviewResult:
        self.do(["inspect review scope"])
        return ReviewResult(summary="ok")
""",
        path="demo.py",
    )

    assert findings == []


def test_lint_source_rejects_workflow_call_keyword_only_parameters() -> None:
    findings = lint_source(
        """
class Role(AgentWorkflow):
    async def __call__(self, *, request: str) -> None:
        self.do(["inspect review scope"])
""",
        path="demo.py",
    )

    assert any(finding.code == "WF402" for finding in findings)


def test_lint_source_rejects_workflow_call_kwargs() -> None:
    findings = lint_source(
        """
class Role(AgentWorkflow):
    async def __call__(self, **kwargs) -> None:
        self.do(["inspect review scope"])
""",
        path="demo.py",
    )

    assert any(finding.code == "WF402" for finding in findings)


def test_lint_source_rejects_untyped_workflow_call_parameter() -> None:
    findings = lint_source(
        """
class Role(AgentWorkflow):
    async def __call__(self, request) -> None:
        self.do(["inspect review scope"])
""",
        path="demo.py",
    )

    assert any(finding.code == "WF403" for finding in findings)


def test_lint_source_rejects_workflow_call_dict_parameter() -> None:
    findings = lint_source(
        """
class Role(AgentWorkflow):
    async def __call__(self, request: dict[str, str]) -> None:
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
    async def __call__(self, request: Any) -> None:
        self.do(["inspect review scope"])
""",
        path="demo.py",
    )

    assert any(finding.code == "WF404" for finding in findings)


def test_lint_source_rejects_workflow_call_dict_return() -> None:
    findings = lint_source(
        """
class Role(AgentWorkflow):
    async def __call__(self) -> dict[str, str]:
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
    async def __call__(self) -> Any:
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
    async def __call__(self) -> None:
        @dataclass
        class FinalizerRequest:
            context_packet: str
""",
        path="demo.py",
    )

    assert any(finding.code == "WF801" for finding in findings)


def test_lint_source_rejects_undeclared_self_method_calls() -> None:
    findings = lint_source(
        """
class Role(AgentWorkflow):
    async def __call__(self) -> None:
        await self.launch_workflow(OtherRole)
""",
        path="demo.py",
    )

    assert any(finding.code == "WF501" for finding in findings)
