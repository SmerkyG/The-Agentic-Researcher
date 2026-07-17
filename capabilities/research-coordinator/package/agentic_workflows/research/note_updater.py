"""Note Updater contract and workflow."""

from __future__ import annotations

from typing import ClassVar, Literal

from agentic_workflows.contract import CommandResult, SubagentWorkflow, Value, WorkflowRecord
from agentic_workflows.fill_spec import field, observe
from agentic_workflows.research.agentic_notes_read import AgenticNotesReadTool
from agentic_workflows.research.agentic_notes_rewrite import AgenticNotesRewriteTool
from agentic_workflows.research.agentic_notes_update import AgenticNotesUpdateTool


class NoteUpdaterResult(WorkflowRecord):
    status: Literal["updated", "skipped", "failed"]


class SkipNote(WorkflowRecord):
    reason: str = Value("Why the proposal is only a temporary workaround or local fix")


class ApplyNote(WorkflowRecord):
    scope: Literal["org", "project", "work"] = Value(
        "Narrowest scope in which the lesson will remain reusable"
    )


class NoteUpdater(SubagentWorkflow[NoteUpdaterResult]):
    """Merge one durable lesson into the narrowest useful scope."""

    agent_name: ClassVar[str] = "note-updater"
    note_update: AgenticNotesUpdateTool

    def workflow(self) -> NoteUpdaterResult:
        with self.agent_request() as triage:
            field(
                "decision",
                SkipNote | ApplyNote,
                "whether to skip this proposal or apply it at the narrowest durable scope",
            )

        match triage.decision:
            case SkipNote():
                return NoteUpdaterResult(status="skipped")
            case ApplyNote(scope=scope):
                self.note_update.target.scope = scope
        update: CommandResult = self.note_update.run()
        if update.returncode != 0:
            return NoteUpdaterResult(status="failed")

        rendered: CommandResult = AgenticNotesReadTool(target=self.note_update.target).run()
        if rendered.returncode != 0:
            return NoteUpdaterResult(status="failed")

        with self.agent_request() as review:
            observe(rendered_note=rendered)
            field(
                "replacement",
                str | None,
                "complete terse replacement note when the rendered note is materially "
                "worse through duplication, verbosity, or scope mismatch; otherwise null",
            )

        if review.replacement is not None:
            rewrite: CommandResult = AgenticNotesRewriteTool(
                target=self.note_update.target,
                content=review.replacement,
            ).run()
            if rewrite.returncode != 0:
                return NoteUpdaterResult(status="failed")

        return NoteUpdaterResult(status="updated")
