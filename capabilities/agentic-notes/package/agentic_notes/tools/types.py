"""Shared structured values for Agentic Notes tools."""

from __future__ import annotations

from typing import Literal

from agentic_tools import Record, Value


class NoteTarget(Record):
    scope: Literal["org", "project", "work"] = Value("Narrowest reusable note scope")
    agent_type: str = Value("Agent type or all-agents")
    note_name: str = Value("Topic name without .md")
    work_branch: str | None = Value("Work branch for work scope", default=None)
