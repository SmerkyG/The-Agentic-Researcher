"""Shared records for ordered research-state finalization."""

from __future__ import annotations

from typing import Literal

from agentic_workflows.contract import WorkflowRecord


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


class FinalizationStateCommitResult(FinalizationWorkspace):
    state_commit: str
    state_changed: bool


class FinalizationReconcileResult(WorkflowRecord):
    """Safe startup repairs plus remaining nonterminal tickets."""

    recovered: list[FinalizationTicket]
    unresolved: list[FinalizationTicket]
