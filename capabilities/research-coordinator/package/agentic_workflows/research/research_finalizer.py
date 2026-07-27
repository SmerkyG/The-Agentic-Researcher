"""Research Finalizer contract and workflow."""

from __future__ import annotations

from typing import ClassVar

from agentic_workflows.contract import SubagentWorkflow, WorkflowRecord
from agentic_workflows.request_spec import AgentRequest, result, step
from agentic_notes.note_updater import NoteUpdater, NoteUpdaterResult
from agentic_notes.tools.update import AgenticNotesUpdateTool
from experiment_log.tools.append import ExperimentLogAppendTool
from agentic_workflows.research.report import ReportAppendTool
from research_finalization.records import FinalizationTicket, FinalizationWorkspace
from research_finalization.tools.commit import FinalizationStateCommitTool
from research_finalization.tools.finish import FinalizationFinishTool
from research_finalization.tools.ready import FinalizationReadyTool


class ResearchFinalizerResult(WorkflowRecord):
    errors: list[str]


class ResearchFinalizer(SubagentWorkflow[ResearchFinalizerResult]):
    """Author and publish records for one committed research result."""

    agent_name: ClassVar[str] = "research-finalizer"
    ticket: FinalizationTicket

    def workflow(self) -> ResearchFinalizerResult:
        errors: list[str] = []
        try:
            workspace: FinalizationWorkspace = FinalizationReadyTool(root=self.ticket.root).run()

            class ReportSection(AgentRequest):
                step(
                    f"The temporary state worktree for this finalization is "
                    f"{workspace.state_dir}. Read condensed_report.md, TODO.md, and "
                    "the latest report page from that worktree."
                )
                report_section: str = result(
                    "complete report section containing goal, hypothesis, method, "
                    "implementation, results, analysis, verification, and next steps",
                )

            report = self.agent_request(ReportSection)

            ReportAppendTool(
                content=report.report_section,
                work_state_dir=workspace.state_dir,
            ).run()

            class Records(AgentRequest):
                step(
                    f"Rewrite {workspace.state_dir}/condensed_report.md with the current synthesis.",
                    f"Update {workspace.state_dir}/TODO.md with completed, autonomous, "
                    "blocked, and user-input work.",
                    guidance=(
                        "Both files belong to the temporary state worktree identified "
                        "in the preceding request."
                    ),
                )
                experiment_log: ExperimentLogAppendTool = result(
                    "append-only experiment record for this completed result",
                )
                note_update: AgenticNotesUpdateTool | None = result(
                    "durable reusable lesson for future agents, or null when none applies",
                )

            records = self.agent_request(Records)

            FinalizationStateCommitTool(root=workspace.root).run()
            records.experiment_log.code.branch = workspace.code_branch
            records.experiment_log.code.commit = workspace.code_commit
            records.experiment_log.run()
        except Exception as error:
            errors.append(str(error))

        FinalizationFinishTool(
            root=self.ticket.root,
            state="failed" if errors else "complete",
            error="; ".join(errors) if errors else None,
        ).run()

        # Notes are optional enrichment, not part of the serialized state/log
        # transaction. Core finalization must be terminal before starting a
        # potentially interruptible subagent so later results cannot be blocked.
        if not errors and records.note_update is not None:
            try:
                note_result: NoteUpdaterResult = NoteUpdater(
                    note_update=records.note_update
                ).run()
                if note_result.status == "failed":
                    errors.append("Note update failed; inspect the note-updater result.")
            except Exception as error:
                errors.append("Note update failed after finalization completed: " + str(error))

        return ResearchFinalizerResult(errors=errors)
