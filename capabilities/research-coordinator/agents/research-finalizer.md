---
name: research-finalizer
kind: subagent
description: Finalize a completed research result after reports are updated.
codex_reasoning_effort: low
renderer: imperative-workflows
workflow_interface: agentic_workflows.research.research_finalizer:ResearchFinalizer
workflow_module: agentic_workflows.research.workflows.research_finalizer
workflow_entry: ResearchFinalizerWorkflow
---

# Research Finalizer

```python agentic-workflow
from __future__ import annotations

from agentic_workflows.research.git import BranchCommitResult, BranchCommitTool
from agentic_workflows.research.note_updater import NoteUpdater, NoteUpdaterResult
from agentic_workflows.research.research_finalizer import ResearchFinalizer, ResearchFinalizerResult
from agentic_workflows.research.research_state import WorkStateCommitResult, WorkStateCommitTool


class ResearchFinalizerWorkflow(ResearchFinalizer):
    """Finalize one result after user-visible records have been updated."""

    def workflow(self) -> ResearchFinalizerResult:
        errors: list[str] = []
        state_result: WorkStateCommitResult = WorkStateCommitTool(
            snapshot_dir=self.work_state_snapshot.snapshot_dir,
            message="work-state: update research records"
        ).run()
        if state_result.state != "complete":
            errors.append("Work-state commit failed; inspect exact command output.")

        if self.note_update is not None:
            note_result: NoteUpdaterResult = NoteUpdater(note_update=self.note_update).run()
            if note_result.status == "failed":
                errors.append("Note update failed; inspect the note-updater result.")

        if self.code_snapshot is not None:
            commit_result: BranchCommitResult = BranchCommitTool(
                snapshot_dir=self.code_snapshot.snapshot_dir,
                background=False,
            ).run()
            if commit_result.state != "committed":
                errors.append("Code snapshot commit did not complete.")
            if self.experiment_log is not None and commit_result.experiment_log_state != "logged":
                errors.append(commit_result.experiment_log_error or "Experiment log update failed.")
        elif self.experiment_log is not None:
            self.experiment_log.run()

        return ResearchFinalizerResult(errors=errors)
```
