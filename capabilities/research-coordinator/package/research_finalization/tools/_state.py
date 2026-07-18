"""Shared durable-state mechanics for finalization tools."""

from __future__ import annotations

from pathlib import Path
import shutil
from typing import Any

from branch_tools.service import drop_branch_worktree
from branch_git_common import git_text, now_iso, safe_load_yaml, slugify, write_yaml
from command_common import runtime_root

from research_finalization.records import FinalizationTicket


TERMINAL_STATES = {"complete", "failed"}


def manifest_path(root: Path) -> Path:
    return root / "manifest.yaml"


def status_path(root: Path) -> Path:
    return root / "status.yaml"


def load_ticket(value: object) -> tuple[Path, dict[str, Any]]:
    root = Path(str(value or "")).expanduser().resolve()
    if not root.is_dir() or not manifest_path(root).is_file():
        raise ValueError(f"finalization ticket does not exist: {root}")
    return root, safe_load_yaml(manifest_path(root))


def update_status(root: Path, **values: object) -> dict[str, Any]:
    path = status_path(root)
    status = safe_load_yaml(path) if path.exists() else {}
    status.update(values)
    status["updated_at"] = now_iso()
    write_yaml(path, status)
    return status


def ticket(root: Path, manifest: dict[str, Any], state: str) -> FinalizationTicket:
    return FinalizationTicket(
        id=str(manifest["id"]),
        root=str(root),
        status_path=str(status_path(root)),
        code_branch=str(manifest["code_branch"]),
        code_commit=str(manifest["code_commit"]),
        state_branch=str(manifest["state_branch"]),
        state=state,
    )


def current_ticket(root: Path, manifest: dict[str, Any]) -> FinalizationTicket:
    state = str(safe_load_yaml(status_path(root)).get("state") or "captured")
    return ticket(root, manifest, state)


def copy_asset(source_root: Path, target_root: Path, relative: str) -> None:
    source = source_root / relative
    if not source.is_file():
        raise ValueError(f"report asset is not a file: {relative}")
    target = target_root / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)


def finish_ticket(
    root: Path,
    manifest: dict[str, Any],
    *,
    state: str,
    error: str | None = None,
) -> FinalizationTicket:
    if state not in TERMINAL_STATES:
        raise ValueError("finish state must be complete or failed")
    current = str(safe_load_yaml(status_path(root)).get("state") or "")
    if current in TERMINAL_STATES:
        if current != state:
            raise ValueError(f"finalization is already terminal with state {current}")
    else:
        if state == "complete" and current != "committed":
            raise ValueError("only a committed finalization can be completed")
        values: dict[str, object] = {"state": state, "finished_at": now_iso()}
        if error:
            values["error"] = error
        update_status(root, **values)
    if state == "complete":
        drop_branch_worktree(
            source_worktree=str(manifest["work_state_dir"]),
            worktree=root / "state",
        )
        shutil.rmtree(root / "assets", ignore_errors=True)
    return ticket(root, manifest, state)
