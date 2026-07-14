---
name: note-updater
kind: subagent
description: Triage and merge one durable reusable lesson into Agentic Notes.
codex_reasoning_effort: medium
renderer: imperative-workflows
workflow_interface: agentic_workflows.research.note_updater:NoteUpdater
workflow_module: agentic_workflows.research.workflows.note_updater
workflow_entry: NoteUpdaterWorkflow
---

# Note Updater

```python agentic-workflow
from __future__ import annotations

from typing import Literal

from agentic_workflows.contract import CommandResult
from agentic_workflows.research.agentic_notes import (
    AgenticNotesReadTool,
    AgenticNotesRewriteTool,
)
from agentic_workflows.research.note_updater import NoteUpdater, NoteUpdaterResult


class NoteUpdaterWorkflow(NoteUpdater):
    """Merge one durable lesson into the narrowest useful scope."""

    def workflow(self) -> NoteUpdaterResult:
        if self.evaluate("the proposed lesson is only a temporary workaround or local fix request"):
            return NoteUpdaterResult(status="skipped")

        scope: Literal["org", "project", "work"] = self.evaluate(
            "narrowest scope in which this lesson will remain reusable"
        )
        self.note_update.target.scope = scope
        update: CommandResult = self.note_update.run()
        if update.returncode != 0:
            return NoteUpdaterResult(status="failed")

        rendered: CommandResult = AgenticNotesReadTool(target=self.note_update.target).run()
        if rendered.returncode != 0:
            return NoteUpdaterResult(status="failed")

        if self.evaluate("the resulting note is materially worse through duplication, verbosity, or scope mismatch"):
            improved: str = self.evaluate("complete terse replacement note content")
            rewrite: CommandResult = AgenticNotesRewriteTool(
                target=self.note_update.target,
                content=improved,
            ).run()
            if rewrite.returncode != 0:
                return NoteUpdaterResult(status="failed")

        return NoteUpdaterResult(status="updated")
```
