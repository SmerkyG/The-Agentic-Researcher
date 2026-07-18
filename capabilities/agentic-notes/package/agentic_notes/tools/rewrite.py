"""Complete note replacement operation."""

from __future__ import annotations

from typing import Literal

from agentic_notes.tools._state import implementation, project_path, target_lock_path
from agentic_notes.tools.types import NoteTarget
from agentic_tools import PythonTool, Record, Value


class AgenticNotesRewriteResult(Record):
    scope: Literal["org", "project", "work"]
    note_name: str
    path: str
    changed: bool
    pushed: bool


class AgenticNotesRewriteTool(PythonTool[AgenticNotesRewriteResult]):
    """Replace one note after a rare cleanup review."""

    target: NoteTarget = Value("Note target")
    content: str = Value("Complete replacement Markdown")
    project_dir: str = Value("Project directory", default=".")

    def execute(self) -> AgenticNotesRewriteResult:
        text = self.content.rstrip() + "\n"
        if not text.strip():
            raise ValueError("replacement note cannot be empty")
        module = implementation()
        project = project_path(self.project_dir)
        lock_path = target_lock_path(
            module,
            scope=self.target.scope,
            project=project,
            work_branch=self.target.work_branch,
        )
        with module.state_lock(lock_path):
            repository, note_path = module.note_path_for_target(
                scope=self.target.scope,
                project_dir=project,
                note_name=self.target.note_name,
                agent_type_value=self.target.agent_type,
                work_branch_value=self.target.work_branch,
            )
            module.pull_ff(repository)
            existing = note_path.read_text(encoding="utf-8") if note_path.exists() else ""
            if existing == text:
                return AgenticNotesRewriteResult(
                    scope=self.target.scope,
                    note_name=module.normalize_note_name(self.target.note_name),
                    path=str(note_path),
                    changed=False,
                    pushed=False,
                )
            note_path.parent.mkdir(parents=True, exist_ok=True)
            note_path.write_text(text, encoding="utf-8")
            changed = module.commit_if_changed(
                repository,
                f"notes: replace {note_path.relative_to(repository)}",
                [note_path],
            )
            pushed = module.push(repository) if changed else False
            if changed and not pushed:
                raise module.AtNotesError("push was rejected")
        return AgenticNotesRewriteResult(
            scope=self.target.scope,
            note_name=module.normalize_note_name(self.target.note_name),
            path=str(note_path),
            changed=changed,
            pushed=pushed,
        )
