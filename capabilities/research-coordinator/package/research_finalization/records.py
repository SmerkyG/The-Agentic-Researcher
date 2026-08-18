"""Structured records shared by finalization tools and workflows."""

from __future__ import annotations

from typing import Literal

from agentic_tools import Record


FinalizationState = Literal["captured", "active", "committed", "complete", "failed"]


class FinalizationTicket(Record):
    """Frozen code identity and staged report assets for one result."""

    id: str
    root: str
    status_path: str
    code_branch: str
    code_commit: str
    records_branch: str
    state: FinalizationState


class FinalizationWorkspace(FinalizationTicket):
    """Temporary worktree created from the latest research-state commit."""

    records_dir: str
    records_base_commit: str


class FinalizationRecordsCommitResult(FinalizationWorkspace):
    records_commit: str
    records_changed: bool


class FinalizationStatusResult(FinalizationTicket):
    """Ticket identity plus durable lifecycle diagnostics."""

    sequence: int | None = None
    created_at: str | None = None
    updated_at: str | None = None
    active_at: str | None = None
    finished_at: str | None = None
    failed_at: str | None = None
    records_commit: str | None = None
    records_changed: bool | None = None
    error: str | None = None


class FinalizationReconcileResult(Record):
    """Safe startup repairs plus remaining nonterminal tickets."""

    recovered: list[FinalizationTicket]
    unresolved: list[FinalizationTicket]
