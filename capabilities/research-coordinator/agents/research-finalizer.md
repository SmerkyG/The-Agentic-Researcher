---
name: research-finalizer
kind: subagent
description: Author and publish records for one committed research result.
codex_reasoning_effort: low
renderer: imperative-workflows
workflow_interface: agentic_workflows.research.research_finalizer:ResearchFinalizer
workflow_module: agentic_workflows.research.workflows.research_finalizer
workflow_entry: ResearchFinalizerWorkflow
---

# Research Finalizer

```python agentic-workflow
from __future__ import annotations

from agentic_workflows.fill_spec import field, observe, step
from agentic_workflows.research.agentic_notes_update import AgenticNotesUpdateTool
from agentic_workflows.research.experiment_log_append import ExperimentLogAppendTool
from agentic_workflows.research.finalization import FinalizationWorkspace
from agentic_workflows.research.finalization_worker import (
    FinalizationFinishTool,
    FinalizationReadyTool,
    FinalizationStateCommitTool,
)
from agentic_workflows.research.note_updater import NoteUpdater, NoteUpdaterResult
from agentic_workflows.research.report import ReportAppendResult, ReportAppendTool
from agentic_workflows.research.research_finalizer import ResearchFinalizer, ResearchFinalizerResult


class ResearchFinalizerWorkflow(ResearchFinalizer):
    """Author and publish records for one committed research result."""

    def workflow(self) -> ResearchFinalizerResult:
        errors: list[str] = []
        try:
            workspace: FinalizationWorkspace = FinalizationReadyTool(root=self.ticket.root).run()
            with self.agent_request() as report:
                observe(finalization_workspace=workspace)
                step(
                    "Read condensed_report.md, TODO.md, and the latest report page from "
                    "`finalization_workspace.state_dir`."
                )
                field(
                    "report_section",
                    str,
                    "complete report section containing goal, hypothesis, method, "
                    "implementation, results, analysis, verification, and next steps",
                )

            report_append: ReportAppendResult = ReportAppendTool(
                content=report.report_section,
                work_state_dir=workspace.state_dir,
            ).run()
            self.observe(report_append_result=report_append)

            with self.agent_request() as records:
                step(
                    "rewrite condensed_report.md in the temporary state worktree with the current synthesis",
                    "update TODO.md in the temporary state worktree with completed, autonomous, blocked, and user-input work",
                    guidance=(
                        "Use `finalization_workspace.state_dir`, already retained from the "
                        "preceding request, as the temporary state worktree."
                    ),
                )
                field(
                    "experiment_log",
                    ExperimentLogAppendTool,
                    "append-only experiment record for this completed result",
                )
                field(
                    "note_update",
                    AgenticNotesUpdateTool | None,
                    "durable reusable lesson for future agents, or null when none applies",
                )

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
```
