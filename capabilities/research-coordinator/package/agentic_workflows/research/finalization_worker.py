"""Finalizer-side operations for publishing captured research state."""

from __future__ import annotations

from typing import ClassVar, Literal

from agentic_workflows.contract import YAMLArgvTool
from agentic_workflows.research.finalization import (
    FinalizationStateCommitResult,
    FinalizationTicket,
    FinalizationWorkspace,
)


class FinalizationReadyTool(YAMLArgvTool[FinalizationWorkspace]):
    """Wait for earlier results and create one latest-state worktree."""

    argv_template: ClassVar[tuple[str, ...]] = ("research-coordinator-finalization", "ready")

    root: str
    timeout_seconds: float = 1800


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
