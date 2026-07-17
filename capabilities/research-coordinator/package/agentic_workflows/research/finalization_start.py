"""Public request contract for freezing one completed research result."""

from __future__ import annotations

from typing import ClassVar

from agentic_workflows.contract import ExecutableWorkflow, Value
from agentic_workflows.research.finalization import FinalizationTicket


class FinalizationStart(ExecutableWorkflow[FinalizationTicket]):
    """Snapshot and commit explicit code paths, then freeze report assets."""

    guidance: ClassVar[str] = (
        "Use explicit code paths, a focused commit message, immutable-snapshot checks, "
        "and work-state-relative report asset paths. Paths that already match HEAD are a "
        "valid replay no-op. The operation is inert until Python calls run()."
    )

    workflow_implementation: ClassVar[str] = (
        "agentic_workflows.research.finalization_start_workflow:FinalizationStartWorkflow"
    )

    code_paths: list[str] = Value(
        "Explicit code paths to snapshot and commit; empty when the result changed no code",
        default_factory=list,
    )
    commit_message: str | None = Value(
        "Focused commit message required when code_paths is nonempty; null otherwise",
        default=None,
    )
    checks: list[str] = Value(
        "Focused, non-redundant commands run against the immutable code snapshot; "
        "empty when code_paths is empty",
        guidance=(
            "For Python checks that use only the standard library, use `uv run --no-project "
            "python ...` so the temporary worktree does not provision every project dependency. "
            "Use ordinary `uv run` only when the check imports project dependencies. "
            "Do not add a separate `py_compile` check when another check executes the same script."
        ),
        default_factory=list,
    )
    report_assets: list[str] = Value(
        "Explicit report-asset paths relative to the work-state directory",
        default_factory=list,
    )
    project_dir: str = "."
    work_state_dir: str | None = None
