"""Update operation for Agentic Notes."""

from __future__ import annotations

from typing import ClassVar

from agentic_workflows.contract import CommandResult, Value, YAMLArgvTool
from agentic_workflows.research.agentic_notes_types import NoteTarget


class AgenticNotesUpdateTool(YAMLArgvTool[CommandResult]):
    """Merge one durable reusable lesson into Agentic Notes."""

    argv_template: ClassVar[tuple[str, ...]] = ("agentic-notes", "update-note")

    target: NoteTarget = Value("Note target")
    summary: str = Value("Compact topic hints, at most 80 characters")
    lesson: str = Value("Final concise reusable guidance")
    rationale: str | None = Value("Why the lesson was learned", default=None)
