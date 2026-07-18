"""Safely reconcile interrupted finalization tickets."""

from __future__ import annotations

from datetime import datetime
import os
from pathlib import Path
from typing import Any

import yaml

from agentic_tools import PythonTool

from research_finalization.records import FinalizationReconcileResult
from research_finalization.tools._state import (
    TERMINAL_STATES,
    current_ticket,
    finish_ticket,
    git_text,
    manifest_path,
    runtime_root,
    safe_load_yaml,
    status_path,
)


def _parse_time(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _matching_experiment_is_logged(manifest: dict[str, Any]) -> bool:
    state_dir = Path(str(manifest["work_state_dir"]))
    state_branch = str(manifest["state_branch"])
    paths = git_text(
        state_dir,
        "ls-tree",
        "-r",
        "--name-only",
        state_branch,
        "--",
        "experiment-log/experiments",
    ).splitlines()
    captured_at = _parse_time(manifest.get("created_at"))
    for relative in paths:
        if not relative.endswith((".yaml", ".yml")):
            continue
        value = yaml.safe_load(git_text(state_dir, "show", f"{state_branch}:{relative}"))
        if not isinstance(value, dict):
            continue
        code = value.get("code")
        if not isinstance(code, dict) or code.get("commit") != manifest.get("code_commit"):
            continue
        if value.get("work_branch") != manifest.get("work_branch"):
            continue
        logged_at = _parse_time(value.get("created_at"))
        if captured_at is None or logged_at is None or logged_at >= captured_at:
            return True
    return False


class FinalizationReconcileTool(PythonTool[FinalizationReconcileResult]):
    """Complete only tickets whose state and experiment record are durable."""

    project_dir: str = "."
    work_branch: str | None = None

    def execute(self) -> FinalizationReconcileResult:
        project_dir = Path(
            self.project_dir or os.environ.get("AR_PROJECT_DIR") or "."
        ).expanduser().resolve()
        branch = self.work_branch or os.environ.get("AR_WORK_BRANCH") or git_text(
            project_dir, "branch", "--show-current"
        )
        roots_dir = runtime_root(project_dir) / "finalizations"
        recovered = []
        unresolved = []
        if not roots_dir.is_dir():
            return FinalizationReconcileResult(recovered=recovered, unresolved=unresolved)

        candidates: list[tuple[int, Path, dict[str, Any]]] = []
        for root in roots_dir.iterdir():
            if not manifest_path(root).is_file() or not status_path(root).is_file():
                continue
            manifest = safe_load_yaml(manifest_path(root))
            if manifest.get("work_branch") != branch:
                continue
            candidates.append((int(manifest.get("sequence") or 0), root, manifest))

        for _sequence, root, manifest in sorted(candidates):
            state = str(safe_load_yaml(status_path(root)).get("state") or "")
            if state in TERMINAL_STATES:
                continue
            if state == "committed" and _matching_experiment_is_logged(manifest):
                finish_ticket(root, manifest, state="complete")
                recovered.append(current_ticket(root, manifest))
            else:
                unresolved.append(current_ticket(root, manifest))
        return FinalizationReconcileResult(recovered=recovered, unresolved=unresolved)
