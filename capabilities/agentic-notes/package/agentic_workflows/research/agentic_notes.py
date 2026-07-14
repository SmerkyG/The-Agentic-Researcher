"""Agentic Notes operation contracts."""

from __future__ import annotations

from typing import ClassVar, Literal

from agentic_workflows.contract import ArgvTool, CommandResult, Value, WorkflowRecord, YAMLArgvTool


class NoteTarget(WorkflowRecord):
    scope: Literal["org", "project", "work"] = Value("Narrowest reusable note scope")
    agent_type: str = Value("Agent type or all-agents")
    note_name: str = Value("Topic name without .md")
    work_branch: str | None = Value("Work branch for work scope", default=None)


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


class AgenticNotesUpdateTool(YAMLArgvTool[CommandResult]):
    """Merge one durable reusable lesson into Agentic Notes."""

    argv_template: ClassVar[tuple[str, ...]] = ("agentic-notes", "update-note")

    target: NoteTarget = Value("Note target")
    summary: str = Value("Compact topic hints, at most 80 characters")
    lesson: str = Value("Final concise reusable guidance")
    rationale: str | None = Value("Why the lesson was learned", default=None)


class AgenticNotesRewriteTool(YAMLArgvTool[CommandResult]):
    """Replace one note after a rare cleanup review."""

    argv_template: ClassVar[tuple[str, ...]] = ("agentic-notes", "rewrite-note")
    target: NoteTarget
    content: str
