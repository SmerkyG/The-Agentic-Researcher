"""Note Updater contract and workflow."""

from __future__ import annotations

from typing import ClassVar, Literal

from agentic_workflows.contract import SubagentWorkflow, Value, WorkflowRecord
from agentic_workflows.request_spec import AgentRequest, result
from agentic_notes.tools.read import AgenticNotesReadTool
from agentic_notes.tools.rewrite import AgenticNotesRewriteTool
from agentic_notes.tools.update import AgenticNotesUpdateTool


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
        class Triage(AgentRequest):
            decision: SkipNote | ApplyNote = result(
                "whether to skip this proposal or apply it at the narrowest durable scope",
            )

        triage = self.agent_request(Triage)

        match triage.decision:
            case SkipNote():
                return NoteUpdaterResult(status="skipped")
            case ApplyNote(scope=scope):
                self.note_update.target.scope = scope
        try:
            self.note_update.run()
            AgenticNotesReadTool(target=self.note_update.target).run()
        except Exception:
            return NoteUpdaterResult(status="failed")

        class Review(AgentRequest):
            replacement: str | None = result(
                "complete terse replacement note when the rendered note is materially "
                "worse through duplication, verbosity, or scope mismatch; otherwise null",
            )

        review = self.agent_request(Review)

        if review.replacement is not None:
            try:
                AgenticNotesRewriteTool(
                    target=self.note_update.target,
                    content=review.replacement,
                ).run()
            except Exception:
                return NoteUpdaterResult(status="failed")

        return NoteUpdaterResult(status="updated")
