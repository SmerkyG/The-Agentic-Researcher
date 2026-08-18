"""Publish a prepared finalization records worktree."""

from __future__ import annotations

from pathlib import Path

from agentic_tools import PythonTool
from branch_tools.service import publish_branch_worktree

from research_finalization.records import FinalizationRecordsCommitResult
from research_finalization.tools._state import (
    load_ticket,
    now_iso,
    safe_load_yaml,
    status_path,
    update_status,
)


class FinalizationRecordsCommitTool(PythonTool[FinalizationRecordsCommitResult]):
    """Publish the temporary research-records worktree to its branch."""

    root: str
    message: str = "branch-records: finalize research result"

    def execute(self) -> FinalizationRecordsCommitResult:
        root, manifest = load_ticket(self.root)
        if safe_load_yaml(status_path(root)).get("state") != "active":
            raise ValueError("finalization must be active before state commit")
        try:
            result = publish_branch_worktree(
                source_worktree=str(manifest["branch_records_dir"]),
                worktree=root / "records",
                branch=str(manifest["records_branch"]),
                base_commit=str(manifest["records_base_commit"]),
                message=self.message,
                push=True,
            )
        except Exception as error:
            update_status(root, state="failed", error=str(error), failed_at=now_iso())
            raise
        update_status(
            root,
            state="committed",
            records_commit=result["commit"],
            records_changed=result["changed"],
        )
        return FinalizationRecordsCommitResult(
            id=str(manifest["id"]),
            root=str(root),
            status_path=str(status_path(root)),
            code_branch=str(manifest["code_branch"]),
            code_commit=str(manifest["code_commit"]),
            records_branch=str(manifest["records_branch"]),
            state="committed",
            records_dir=str(root / "records"),
            records_base_commit=str(manifest["records_base_commit"]),
            records_commit=str(result["commit"]),
            records_changed=bool(result["changed"]),
        )
