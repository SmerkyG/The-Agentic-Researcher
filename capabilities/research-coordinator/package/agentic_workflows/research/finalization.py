"""Ordered research-state finalization operation contracts."""

from __future__ import annotations

from typing import ClassVar, Literal

from agentic_workflows.contract import Value, WorkflowRecord, YAMLArgvTool


class FinalizationTicket(WorkflowRecord):
    """Frozen code identity and staged report assets for one result."""

    id: str
    root: str
    status_path: str
    code_branch: str
    code_commit: str
    state_branch: str
    state: Literal["captured", "active", "committed", "complete", "failed"]


class FinalizationWorkspace(FinalizationTicket):
    """Temporary worktree created from the latest research-state commit."""

    state_dir: str
    state_base_commit: str


class FinalizationCaptureTool(YAMLArgvTool[FinalizationTicket]):
    """Record the current code commit and freeze explicit report assets."""

    argv_template: ClassVar[tuple[str, ...]] = ("research-coordinator-finalization", "capture")

    report_assets: list[str] = Value("Explicit work-state figure and report-asset paths", default_factory=list)
    project_dir: str = "."
    work_state_dir: str | None = None


class FinalizationReadyTool(YAMLArgvTool[FinalizationWorkspace]):
    """Wait for earlier results and create one latest-state worktree."""

    argv_template: ClassVar[tuple[str, ...]] = ("research-coordinator-finalization", "ready")

    root: str
    timeout_seconds: float = 1800


class FinalizationStateCommitResult(FinalizationWorkspace):
    state_commit: str
    state_changed: bool


class FinalizationStateCommitTool(YAMLArgvTool[FinalizationStateCommitResult]):
    """Publish the temporary research-state worktree to its branch."""

    argv_template: ClassVar[tuple[str, ...]] = ("research-coordinator-finalization", "commit")

    root: str
    message: str = "work-state: finalize research result"


class FinalizationFinishTool(YAMLArgvTool[FinalizationTicket]):
    """Persist terminal status and clean a successful temporary worktree."""

    argv_template: ClassVar[tuple[str, ...]] = ("research-coordinator-finalization", "finish")

    root: str
    state: Literal["complete", "failed"]
    error: str | None = None


class FinalizationStatusTool(YAMLArgvTool[FinalizationTicket]):
    """Read durable finalization status without inspecting a child agent."""

    argv_template: ClassVar[tuple[str, ...]] = ("research-coordinator-finalization", "status")

    root: str
