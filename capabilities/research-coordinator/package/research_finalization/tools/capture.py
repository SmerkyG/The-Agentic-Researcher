"""Capture a frozen code identity and report assets for finalization."""

from __future__ import annotations

import os
from pathlib import Path, PurePosixPath
import shutil
import time

from agentic_tools import PythonTool, Value

from research_finalization.records import FinalizationTicket
from research_finalization.tools._state import (
    copy_asset,
    git_text,
    manifest_path,
    now_iso,
    runtime_root,
    slugify,
    status_path,
    ticket,
    update_status,
    write_yaml,
)


def _explicit_path(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("report_assets must contain non-empty paths")
    path = PurePosixPath(value)
    if path.is_absolute() or path == PurePosixPath(".") or ".." in path.parts or ".git" in path.parts:
        raise ValueError(
            f"report asset path must be relative to the work-state directory without .git or ..: {value}"
        )
    if any(character in value for character in "*?["):
        raise ValueError(f"report asset path must not contain a glob: {value}")
    return path.as_posix()


class FinalizationCaptureTool(PythonTool[FinalizationTicket]):
    """Record the current code commit and freeze explicit report assets."""

    report_assets: list[str] = Value(
        "Explicit report-asset paths relative to the work-state directory",
        default_factory=list,
    )
    project_dir: str | None = None
    work_state_dir: str | None = None

    def execute(self) -> FinalizationTicket:
        project_dir = Path(
            self.project_dir or os.environ.get("AR_PROJECT_DIR") or "."
        ).expanduser().resolve()
        work_state_value = self.work_state_dir or os.environ.get("AR_WORK_STATE_DIR")
        if not work_state_value:
            raise ValueError("work_state_dir or AR_WORK_STATE_DIR is required")
        work_state_dir = Path(work_state_value).expanduser().resolve()
        code_branch = git_text(project_dir, "branch", "--show-current")
        state_branch = git_text(work_state_dir, "branch", "--show-current")
        if not code_branch or not state_branch:
            raise ValueError("finalization capture requires named code and state branches")
        code_commit = git_text(project_dir, "rev-parse", "HEAD")
        report_assets = list(dict.fromkeys(_explicit_path(value) for value in self.report_assets))

        sequence = time.time_ns()
        finalization_id = f"{sequence}-{os.getpid()}-{slugify(code_branch)}"
        root = runtime_root(project_dir) / "finalizations" / finalization_id
        assets_dir = root / "assets"
        root.mkdir(parents=True)
        try:
            for relative in report_assets:
                copy_asset(work_state_dir, assets_dir, relative)
        except Exception:
            shutil.rmtree(root, ignore_errors=True)
            raise

        created_at = now_iso()
        manifest = {
            "version": 2,
            "id": finalization_id,
            "sequence": sequence,
            "created_at": created_at,
            "project_dir": str(project_dir),
            "work_state_dir": str(work_state_dir),
            "work_branch": str(os.environ.get("AR_WORK_BRANCH") or code_branch),
            "code_branch": code_branch,
            "code_commit": code_commit,
            "state_branch": state_branch,
            "report_assets": report_assets,
        }
        write_yaml(manifest_path(root), manifest)
        update_status(
            root,
            id=finalization_id,
            sequence=sequence,
            state="captured",
            created_at=created_at,
        )
        return ticket(root, manifest, "captured")
