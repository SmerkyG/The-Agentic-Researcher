"""Durable note update operation."""

from __future__ import annotations

from typing import Literal

from agentic_notes.tools._state import implementation, project_path, target_lock_path
from agentic_notes.tools.types import NoteTarget
from agentic_tools import PythonTool, Record, Value


class AgenticNotesUpdateResult(Record):
    scope: Literal["org", "project", "work"]
    note_name: str
    repository: str
    changed: bool
    pushed: bool


class AgenticNotesUpdateTool(PythonTool[AgenticNotesUpdateResult]):
    """Merge one durable reusable lesson into Agentic Notes."""

    target: NoteTarget = Value("Note target")
    summary: str = Value("Compact topic hints, at most 80 characters")
    lesson: str = Value("Final concise reusable guidance")
    rationale: str | None = Value("Why the lesson was learned", default=None)
    project_dir: str = Value("Project directory", default=".")

    def execute(self) -> AgenticNotesUpdateResult:
        module = implementation()
        project = project_path(self.project_dir)
        request = {
            "kind": "note_update_request",
            "target": {
                "scope": self.target.scope,
                "agent_type": self.target.agent_type,
                "note_name": self.target.note_name,
                **({"work_branch": self.target.work_branch} if self.target.work_branch else {}),
            },
            "summary": self.summary,
            "lesson": self.lesson,
            **({"rationale": self.rationale} if self.rationale is not None else {}),
        }
        lock_path = target_lock_path(
            module,
            scope=self.target.scope,
            project=project,
            work_branch=self.target.work_branch,
        )
        with module.state_lock(lock_path):
            for attempt in range(2):
                repository, changed = module.update_note_once(request, project)
                if not changed:
                    return AgenticNotesUpdateResult(
                        scope=self.target.scope,
                        note_name=module.normalize_note_name(self.target.note_name),
                        repository=str(repository),
                        changed=False,
                        pushed=False,
                    )
                if module.push(repository):
                    return AgenticNotesUpdateResult(
                        scope=self.target.scope,
                        note_name=module.normalize_note_name(self.target.note_name),
                        repository=str(repository),
                        changed=True,
                        pushed=True,
                    )
                if attempt == 0:
                    branch = module.current_branch(repository) or module.state_branch()
                    module.git(repository, "fetch", "origin")
                    module.git(repository, "reset", "--hard", f"origin/{branch}")
        raise module.AtNotesError("push was rejected after retry; note update may need manual help")
