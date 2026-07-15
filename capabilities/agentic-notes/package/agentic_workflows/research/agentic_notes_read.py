"""Read operations for Agentic Notes."""

from __future__ import annotations

from typing import ClassVar

from agentic_workflows.contract import ArgvTool, CommandResult
from agentic_workflows.research.agentic_notes_types import NoteTarget


class AgenticNotesReadTopicTool(ArgvTool[CommandResult]):
    """Read one rendered on-demand note topic."""

    argv_template: ClassVar[tuple[str, ...]] = ("agentic-notes", "read-note")
    topic: str
    agent_type: str = "research-coordinator"

    def argv(self) -> list[str]:
        return [
            *self.argv_template,
            "--project-dir", ".",
            "--agent-type", self.agent_type,
            self.topic,
        ]


class AgenticNotesReadTool(ArgvTool[CommandResult]):
    """Read one rendered note by target."""

    argv_template: ClassVar[tuple[str, ...]] = ("agentic-notes", "read-note")
    target: NoteTarget

    def argv(self) -> list[str]:
        return [
            *self.argv_template,
            "--project-dir", ".",
            "--agent-type", self.target.agent_type,
            self.target.note_name,
        ]
