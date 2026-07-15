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

from agentic_workflows.research.agentic_notes_update import AgenticNotesUpdateTool
from agentic_workflows.research.experiment_log_append import ExperimentLogAppendTool
from agentic_workflows.research.finalization import FinalizationWorkspace
from agentic_workflows.research.finalization_worker import (
    FinalizationFinishTool,
    FinalizationReadyTool,
    FinalizationStateCommitTool,
)
from agentic_workflows.research.note_updater import NoteUpdater, NoteUpdaterResult
from agentic_workflows.research.report import ReportAppendTool
from agentic_workflows.research.research_finalizer import ResearchFinalizer, ResearchFinalizerResult


class ResearchFinalizerWorkflow(ResearchFinalizer):
    """Author and publish records for one committed research result."""

    def workflow(self) -> ResearchFinalizerResult:
        errors: list[str] = []
        try:
            workspace: FinalizationWorkspace = FinalizationReadyTool(root=self.ticket.root).run()
            self.do(
                ["read condensed_report.md, TODO.md, and the latest report page from the temporary state worktree"],
                guidance="Use workspace.state_dir as the temporary state worktree path.",
            )

            report_section: str = self.evaluate(
                "complete report section containing goal, hypothesis, method, implementation, results, analysis, verification, and next steps"
            )
            ReportAppendTool(content=report_section, work_state_dir=workspace.state_dir).run()
            self.do(
                [
                    "rewrite condensed_report.md in the temporary state worktree with the current synthesis",
                    "update TODO.md in the temporary state worktree with completed, autonomous, blocked, and user-input work",
                ],
                guidance="Use workspace.state_dir as the temporary state worktree path.",
            )
            experiment_log: ExperimentLogAppendTool = self.fill(ExperimentLogAppendTool)
            note_update: AgenticNotesUpdateTool | None = None
            if self.evaluate("this work produced a durable reusable lesson for future agents"):
                filled_note_update: AgenticNotesUpdateTool = self.fill(AgenticNotesUpdateTool)
                note_update = filled_note_update

            FinalizationStateCommitTool(root=workspace.root).run()
            experiment_log.code.branch = workspace.code_branch
            experiment_log.code.commit = workspace.code_commit
            experiment_log.run()

            if note_update is not None:
                note_result: NoteUpdaterResult = NoteUpdater(note_update=note_update).run()
                if note_result.status == "failed":
                    errors.append("Note update failed; inspect the note-updater result.")
        except Exception as error:
            errors.append(str(error))

        FinalizationFinishTool(
            root=self.ticket.root,
            state="failed" if errors else "complete",
            error="; ".join(errors) if errors else None,
        ).run()

        return ResearchFinalizerResult(errors=errors)
```
