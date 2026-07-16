"""Public request contract for freezing one completed research result."""

from __future__ import annotations

from typing import ClassVar

from agentic_workflows.contract import ExecutableWorkflow, Value
from agentic_workflows.research.finalization import FinalizationTicket


class FinalizationStart(ExecutableWorkflow[FinalizationTicket]):
    """Snapshot and commit explicit code paths, then freeze report assets."""

    workflow_implementation: ClassVar[str] = (
        "agentic_workflows.research.finalization_start_workflow:FinalizationStartWorkflow"
    )

    code_paths: list[str] = Value(
        "Explicit code paths to snapshot and commit; empty when the result changed no code",
        default_factory=list,
    )
    commit_message: str | None = Value(
        "Focused commit message required when code_paths is nonempty",
        default=None,
    )
    checks: list[str] = Value(
        "Focused commands run against the immutable code snapshot",
        default_factory=list,
    )
    report_assets: list[str] = Value(
        "Explicit report-asset paths relative to the work-state directory",
        default_factory=list,
    )
    project_dir: str = "."
    work_state_dir: str | None = None
