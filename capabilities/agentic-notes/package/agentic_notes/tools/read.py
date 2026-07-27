"""Rendered note read operations."""

from __future__ import annotations

from agentic_notes.tools._state import read_parts
from agentic_notes.tools.types import NoteTarget
from agentic_tools import PythonTool, Record, Value


class AgenticNotesReadResult(Record):
    note_name: str
    agent_type: str
    content: str
    portions: list[str]


def _read_result(note_name: str, agent_type: str | None, project_dir: str) -> AgenticNotesReadResult:
    normalized_name, active_agent_type, parts = read_parts(
        note_name=note_name,
        agent_type=agent_type,
        project_dir=project_dir,
    )
    lines = [
        f"# Agentic Note: {normalized_name}",
        "",
        f"Agent type: `{active_agent_type}`",
        "",
        "This rendered note combines every available portion for the current "
        "project, work branch, and agent type.",
        "",
    ]
    for label, text in parts:
        lines.extend([f"## {label}", "", text, ""])
    return AgenticNotesReadResult(
        note_name=normalized_name,
        agent_type=active_agent_type,
        content="\n".join(lines).rstrip(),
        portions=[label for label, _ in parts],
    )


class AgenticNotesReadTopicTool(PythonTool[AgenticNotesReadResult]):
    """Read one rendered on-demand note topic."""

    topic: str = Value("Note topic without .md")
    agent_type: str | None = Value("Agent type; defaults to the active main agent", default=None)
    project_dir: str = Value("Project directory", default=".")

    def execute(self) -> AgenticNotesReadResult:
        return _read_result(self.topic, self.agent_type, self.project_dir)


class AgenticNotesReadTool(PythonTool[AgenticNotesReadResult]):
    """Read one rendered note by target."""

    target: NoteTarget = Value("Note target")
    project_dir: str = Value("Project directory", default=".")

    def execute(self) -> AgenticNotesReadResult:
        return _read_result(self.target.note_name, self.target.agent_type, self.project_dir)
