"""Prepare a serialized research-state worktree for one finalization."""

from __future__ import annotations

from pathlib import Path
import time
from typing import Any

from agentic_tools import PythonTool
from branch_tools.service import create_branch_worktree, drop_branch_worktree

from research_finalization.records import FinalizationWorkspace
from research_finalization.tools._state import (
    TERMINAL_STATES,
    copy_asset,
    load_ticket,
    manifest_path,
    now_iso,
    safe_load_yaml,
    status_path,
    update_status,
    write_yaml,
)


def _prior_tickets(root: Path, manifest: dict[str, Any]) -> list[Path]:
    tickets: list[tuple[int, Path]] = []
    for candidate in root.parent.iterdir():
        if candidate == root or not manifest_path(candidate).is_file() or not status_path(candidate).is_file():
            continue
        other = safe_load_yaml(manifest_path(candidate))
        if other.get("work_branch") != manifest.get("work_branch"):
            continue
        sequence = int(other.get("sequence") or 0)
        if sequence < int(manifest["sequence"]):
            tickets.append((sequence, candidate))
    return [ticket for _, ticket in sorted(tickets)]


class FinalizationReadyTool(PythonTool[FinalizationWorkspace]):
    """Wait for earlier results and create one latest-state worktree."""

    root: str
    timeout_seconds: float = 1800

    def execute(self) -> FinalizationWorkspace:
        root, manifest = load_ticket(self.root)
        deadline = time.monotonic() + self.timeout_seconds
        while True:
            blocking = [
                candidate
                for candidate in _prior_tickets(root, manifest)
                if safe_load_yaml(status_path(candidate)).get("state") not in TERMINAL_STATES
            ]
            if not blocking:
                break
            if time.monotonic() >= deadline:
                raise ValueError(
                    "timed out waiting for earlier finalizations: "
                    + ", ".join(path.name for path in blocking)
                )
            time.sleep(0.5)

        work_state_dir = Path(str(manifest["work_state_dir"]))
        state_dir = root / "state"
        workspace = create_branch_worktree(
            source_worktree=work_state_dir,
            worktree=state_dir,
        )
        if workspace["branch"] != manifest["state_branch"]:
            drop_branch_worktree(source_worktree=work_state_dir, worktree=state_dir)
            raise ValueError("work-state branch changed since finalization capture")
        for relative in manifest.get("report_assets", []):
            copy_asset(root / "assets", state_dir, str(relative))
        manifest["state_base_commit"] = workspace["base_commit"]
        manifest["ready_at"] = now_iso()
        write_yaml(manifest_path(root), manifest)
        update_status(root, state="active", active_at=manifest["ready_at"])
        return FinalizationWorkspace(
            id=str(manifest["id"]),
            root=str(root),
            status_path=str(status_path(root)),
            code_branch=str(manifest["code_branch"]),
            code_commit=str(manifest["code_commit"]),
            state_branch=str(manifest["state_branch"]),
            state="active",
            state_dir=str(state_dir),
            state_base_commit=str(workspace["base_commit"]),
        )
