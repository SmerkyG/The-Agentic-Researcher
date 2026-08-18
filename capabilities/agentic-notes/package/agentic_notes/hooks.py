"""Package-native lifecycle hooks for Agentic Notes."""

from __future__ import annotations

import os
from pathlib import Path
import shutil
from types import SimpleNamespace
import sys

from agentic_notes import state


def _required(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise ValueError(f"{name} is required")
    return value


def _truthy(value: str) -> bool:
    return value.lower() not in {"0", "false", "no", "off"}


def setup() -> None:
    project_dir = Path(_required("AT_PROJECT_DIR")).resolve()
    org_repo = os.environ.get("AR_ORG_NOTES_REPO")
    if org_repo:
        try:
            state.init_org_notes(SimpleNamespace(repo=org_repo))
        except Exception as error:
            print(f"Warning: Could not initialize org repo checkout: {error}", file=sys.stderr)

    if not _truthy(os.environ.get("AR_NOTES_AUTO_REFRESH", "true")):
        state.ensure_project_state(project_dir, pull_remote=False, push_changes=False)
    elif os.environ.get("AR_NOTES_REFRESH_MODE", "periodic") == "foreground":
        try:
            state.refresh(SimpleNamespace(project_dir=str(project_dir)))
        except Exception as error:
            print(f"Warning: Could not refresh Agentic Notes checkouts: {error}", file=sys.stderr)
    else:
        state.ensure_project_state(project_dir, pull_remote=False, push_changes=False)


def post_compaction() -> None:
    state.refresh(SimpleNamespace(project_dir=_required("AT_PROJECT_DIR")))


def refresh_loop() -> None:
    state.refresh_loop(
        SimpleNamespace(
            project_dir=_required("AT_PROJECT_DIR"),
            heartbeat_dir=_required("AT_HEARTBEAT_DIR"),
            interval_seconds=int(os.environ.get("AT_REFRESH_INTERVAL_SECONDS") or 120),
            stale_seconds=int(os.environ.get("AT_STALE_SECONDS") or 300),
        )
    )


def create_work() -> None:
    source_records = Path(_required("AT_CREATE_SOURCE_RECORDS_DIR"))
    new_records = Path(_required("AT_CREATE_NEW_RECORDS_DIR"))
    source_notes = source_records / "agent-notes"
    new_notes = new_records / "agent-notes"

    if not source_notes.is_dir():
        print("No inherited Agentic Notes to copy.")
        return
    if source_notes.resolve() == new_notes.resolve():
        print("Source and destination Agentic Notes are the same; nothing to copy.")
        return

    copied: list[str] = []
    skipped: list[str] = []
    for source_path in sorted(source_notes.rglob("*")):
        if not source_path.is_file() or source_path.name == ".gitkeep":
            continue
        relative = source_path.relative_to(source_notes)
        target_path = new_notes / relative
        target_path.parent.mkdir(parents=True, exist_ok=True)
        if target_path.exists() and target_path.read_text(encoding="utf-8") != "":
            skipped.append(str(relative))
            continue
        shutil.copy2(source_path, target_path)
        copied.append(str(relative))

    if copied:
        print(f"Copied {len(copied)} inherited Agentic Notes file(s).")
    if skipped:
        print(f"Skipped {len(skipped)} existing non-empty Agentic Notes file(s).")
    if not copied and not skipped:
        print("No inherited Agentic Notes files found.")
