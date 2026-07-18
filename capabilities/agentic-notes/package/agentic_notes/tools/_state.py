"""Private shared state machinery for Agentic Notes tools."""

from __future__ import annotations

from contextlib import ExitStack
import os
from pathlib import Path
from types import ModuleType
from typing import Literal

from agentic_notes import state


Scope = Literal["org", "project", "work"]
def implementation() -> ModuleType:
    return state


def project_path(value: str | Path) -> Path:
    return Path(value).expanduser().resolve()


def read_lock_paths(module: ModuleType, project: Path) -> list[Path]:
    paths: list[Path] = []
    if os.environ.get("AR_ORG_NOTES_REPO"):
        paths.append(module.lock_file_for("org-agentic-notes"))
    paths.append(module.lock_file_for("project", project))
    active_work_branch = os.environ.get("AR_WORK_BRANCH")
    if active_work_branch:
        paths.append(
            module.lock_file_for(
                f"work-{module.work_branch_id(active_work_branch)}",
                project,
            )
        )
    return sorted(set(paths))


def read_parts(
    *,
    note_name: str,
    agent_type: str | None,
    project_dir: str | Path,
) -> tuple[str, str, list[tuple[str, str]]]:
    module = implementation()
    project = project_path(project_dir)
    active_agent_type = module.agent_type(agent_type)
    normalized_name = module.normalize_note_name(note_name)
    with ExitStack() as stack:
        for path in read_lock_paths(module, project):
            stack.enter_context(module.state_lock(path))
        parts = module.compose_scoped_note(project, active_agent_type, normalized_name)
    if not parts:
        raise module.AtNotesError(
            f"no rendered note found for topic {normalized_name!r} "
            f"and agent type {active_agent_type!r}"
        )
    return normalized_name, active_agent_type, parts


def target_lock_path(
    module: ModuleType,
    *,
    scope: Scope,
    project: Path,
    work_branch: str | None,
) -> Path:
    if scope == "org":
        return module.lock_file_for("org-agentic-notes")
    if scope == "project":
        return module.lock_file_for("project", project)
    return module.lock_file_for(
        f"work-{module.work_branch_id(work_branch)}",
        project,
    )
