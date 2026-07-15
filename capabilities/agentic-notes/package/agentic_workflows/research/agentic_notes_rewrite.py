"""Rewrite operation for Agentic Notes."""

from __future__ import annotations

from typing import ClassVar

from agentic_workflows.contract import CommandResult, YAMLArgvTool
from agentic_workflows.research.agentic_notes_types import NoteTarget


class AgenticNotesRewriteTool(YAMLArgvTool[CommandResult]):
    """Replace one note after a rare cleanup review."""

    argv_template: ClassVar[tuple[str, ...]] = ("agentic-notes", "rewrite-note")
    target: NoteTarget
    content: str
