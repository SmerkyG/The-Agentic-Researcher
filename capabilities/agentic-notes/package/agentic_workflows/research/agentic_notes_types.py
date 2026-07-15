"""Shared Agentic Notes operation records."""

from __future__ import annotations

from typing import Literal

from agentic_workflows.contract import Value, WorkflowRecord


class NoteTarget(WorkflowRecord):
    scope: Literal["org", "project", "work"] = Value("Narrowest reusable note scope")
    agent_type: str = Value("Agent type or all-agents")
    note_name: str = Value("Topic name without .md")
    work_branch: str | None = Value("Work branch for work scope", default=None)
