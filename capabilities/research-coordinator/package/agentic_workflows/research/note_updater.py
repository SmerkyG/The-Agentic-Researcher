"""Public Note Updater contract."""

from __future__ import annotations

from typing import ClassVar, Literal

from agentic_workflows.contract import SubagentWorkflow, WorkflowRecord
from agentic_workflows.research.agentic_notes_update import AgenticNotesUpdateTool


class NoteUpdaterResult(WorkflowRecord):
    status: Literal["updated", "skipped", "failed"]


class NoteUpdater(SubagentWorkflow[NoteUpdaterResult]):
    """Invocation contract for durable lesson triage."""

    agent_name: ClassVar[str] = "note-updater"
    note_update: AgenticNotesUpdateTool
