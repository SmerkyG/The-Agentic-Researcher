"""Publish a prepared finalization state worktree."""

from __future__ import annotations

from pathlib import Path

from agentic_tools import PythonTool
from branch_tools.service import publish_branch_worktree

from research_finalization.records import FinalizationStateCommitResult
from research_finalization.tools._state import (
    load_ticket,
    now_iso,
    safe_load_yaml,
    status_path,
    update_status,
)


class FinalizationStateCommitTool(PythonTool[FinalizationStateCommitResult]):
    """Publish the temporary research-state worktree to its branch."""

    root: str
    message: str = "work-state: finalize research result"

    def execute(self) -> FinalizationStateCommitResult:
        root, manifest = load_ticket(self.root)
        if safe_load_yaml(status_path(root)).get("state") != "active":
            raise ValueError("finalization must be active before state commit")
        try:
            result = publish_branch_worktree(
                source_worktree=str(manifest["work_state_dir"]),
                worktree=root / "state",
                branch=str(manifest["state_branch"]),
                base_commit=str(manifest["state_base_commit"]),
                message=self.message,
                push=True,
            )
        except Exception as error:
            update_status(root, state="failed", error=str(error), failed_at=now_iso())
            raise
        update_status(
            root,
            state="committed",
            state_commit=result["commit"],
            state_changed=result["changed"],
        )
        return FinalizationStateCommitResult(
            id=str(manifest["id"]),
            root=str(root),
            status_path=str(status_path(root)),
            code_branch=str(manifest["code_branch"]),
            code_commit=str(manifest["code_commit"]),
            state_branch=str(manifest["state_branch"]),
            state="committed",
            state_dir=str(root / "state"),
            state_base_commit=str(manifest["state_base_commit"]),
            state_commit=str(result["commit"]),
            state_changed=bool(result["changed"]),
        )
