"""Isolated research finalization operation contracts."""

from __future__ import annotations

from typing import ClassVar, Literal

from agentic_workflows.contract import Value, WorkflowRecord, YAMLArgvTool


class FinalizationWorkspace(WorkflowRecord):
    """Private copy-on-write views for one completed research result."""

    id: str
    root: str
    code_dir: str
    state_dir: str
    status_path: str
    code_snapshot_dir: str | None
    code_branch: str
    code_base_commit: str
    state_branch: str
    state_base_commit: str
    state: Literal["captured", "active", "applied", "complete", "failed"]


class FinalizationForkTool(YAMLArgvTool[FinalizationWorkspace]):
    """Freeze completed code and report assets into private Git worktrees."""

    argv_template: ClassVar[tuple[str, ...]] = ("research-coordinator-finalization", "fork")

    code_snapshot_dir: str | None = Value("Branch snapshot directory for changed code, or None")
    state_assets: list[str] = Value("Explicit work-state figure and report-asset paths", default_factory=list)
    project_dir: str = "."
    work_state_dir: str | None = None


class FinalizationReadyTool(YAMLArgvTool[FinalizationWorkspace]):
    """Wait for earlier results, then refresh the private state view."""

    argv_template: ClassVar[tuple[str, ...]] = ("research-coordinator-finalization", "ready")

    root: str
    timeout_seconds: float = 1800


class FinalizationApplyResult(FinalizationWorkspace):
    code_commit: str
    code_changed: bool
    state_commit: str
    state_changed: bool


class FinalizationApplyTool(YAMLArgvTool[FinalizationApplyResult]):
    """Verify and integrate private code and research-state views in order."""

    argv_template: ClassVar[tuple[str, ...]] = ("research-coordinator-finalization", "apply")

    root: str
    state_message: str = "work-state: finalize research result"


class FinalizationFinishTool(YAMLArgvTool[FinalizationWorkspace]):
    """Persist terminal status and clean successful private worktrees."""

    argv_template: ClassVar[tuple[str, ...]] = ("research-coordinator-finalization", "finish")

    root: str
    state: Literal["complete", "failed"]
    error: str | None = None


class FinalizationStatusTool(YAMLArgvTool[FinalizationWorkspace]):
    """Read durable finalization status without inspecting a child agent."""

    argv_template: ClassVar[tuple[str, ...]] = ("research-coordinator-finalization", "status")

    root: str
