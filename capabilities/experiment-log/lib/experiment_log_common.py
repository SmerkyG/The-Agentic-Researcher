"""Experiment-log capability state and schema operations."""

from __future__ import annotations

import datetime as dt
from pathlib import Path
import re
import sys
from typing import Any, Callable


REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "scripts" / "lib" / "commands"))

from agentic_state import (  # noqa: E402
    AgenticStateError,
    commit_if_changed,
    ensure_work_state,
    git,
    push,
    safe_load_yaml,
    slugify,
    state_lock,
    user_id,
    work_branch,
    work_lock_path,
    work_state_branch,
    write_yaml,
)


class ExperimentLogError(RuntimeError):
    pass


def initial_summary() -> str:
    return "\n".join(
        [
            "# Experiment Summary",
            "",
            "| Experiment | User | Status | Description | Key Result | Commit |",
            "| --- | --- | --- | --- | --- | --- |",
            "",
        ]
    )


def experiment_log_dir(repo: Path) -> Path:
    return repo / "experiment-log"


def ensure_experiment_log_files(repo: Path, branch_name: str) -> list[Path]:
    changed_paths: list[Path] = []
    log_dir = experiment_log_dir(repo)
    experiments_dir = log_dir / "experiments"
    experiments_dir.mkdir(parents=True, exist_ok=True)

    counter = log_dir / "COUNTER.yaml"
    if not counter.exists():
        write_yaml(
            counter,
            {
                "schema_version": 1,
                "work_branch": work_branch(branch_name),
                "next_experiment_number": 1,
            },
        )
        changed_paths.append(counter)

    summary = log_dir / "SUMMARY.md"
    if not summary.exists():
        summary.write_text(initial_summary(), encoding="utf-8")
        changed_paths.append(summary)

    keep = experiments_dir / ".gitkeep"
    if not any(p.name != ".gitkeep" for p in experiments_dir.iterdir()):
        keep.touch()
        changed_paths.append(keep)

    return changed_paths


def read_summary(project_dir: Path, branch_name: str) -> str:
    repo = ensure_work_state(project_dir, branch_name, pull_remote=False)
    path = experiment_log_dir(repo) / "SUMMARY.md"
    if not path.exists():
        raise ExperimentLogError(f"experiment summary does not exist on {work_state_branch(branch_name)}")
    return path.read_text(encoding="utf-8").rstrip()


def load_counter(log_dir: Path) -> dict[str, Any]:
    counter_path = log_dir / "COUNTER.yaml"
    data = safe_load_yaml(counter_path)
    data.setdefault("schema_version", 1)
    data.setdefault("next_experiment_number", 1)
    return data


def qualified_experiment_ref(branch_name: str, experiment_id: str) -> str:
    return f"{work_branch(branch_name)}::{experiment_id}"


def split_experiment_ref(raw_ref: str, current_work_branch: str) -> tuple[str, str]:
    ref = str(raw_ref or "").strip()
    if not ref:
        raise ExperimentLogError("experiment reference cannot be empty")
    if "\\" in ref or ref in {".", ".."}:
        raise ExperimentLogError(f"invalid experiment reference: {ref}")
    if "::" in ref:
        raw_work_branch, experiment_id = ref.split("::", 1)
        branch_name = work_branch(raw_work_branch)
    else:
        branch_name = work_branch(current_work_branch)
        experiment_id = ref
    if "/" in experiment_id or experiment_id in {"", ".", ".."}:
        raise ExperimentLogError(f"invalid experiment id: {experiment_id}")
    return branch_name, experiment_id


def append_summary_row(summary_path: Path, row: str) -> None:
    text = summary_path.read_text(encoding="utf-8") if summary_path.exists() else initial_summary()
    if not text.endswith("\n"):
        text += "\n"
    summary_path.write_text(text + row + "\n", encoding="utf-8")


def short_commit(request: dict[str, Any]) -> str:
    code = request.get("code")
    if isinstance(code, dict):
        commit = str(code.get("commit") or "").strip()
        if commit:
            return commit[:7]
    return ""


def request_successful(request: dict[str, Any]) -> bool:
    value = request.get("success", False)
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "on", "success", "successful"}


def code_commit(request: dict[str, Any]) -> str:
    code = request.get("code")
    if isinstance(code, dict):
        return str(code.get("commit") or "").strip()
    return ""


def success_tag_name(branch_name: str, experiment_id: str) -> str:
    return f"exp/{work_branch(branch_name)}/{experiment_id}-success"


def tag_successful_experiment(request: dict[str, Any], project_dir: Path, branch_name: str, generated_id: str) -> None:
    if not request_successful(request):
        return
    if str(request.get("status") or "completed").strip().lower() not in {"completed", "success", "successful"}:
        raise ExperimentLogError("success tags require a completed/successful experiment status")

    _, experiment_id = split_experiment_ref(generated_id, branch_name)
    commit = code_commit(request)
    if not commit:
        raise ExperimentLogError("success tags require code.commit in the experiment request")

    tag_name = success_tag_name(branch_name, experiment_id)
    git(project_dir, "check-ref-format", f"refs/tags/{tag_name}")
    resolved_commit = git(project_dir, "rev-parse", "--verify", f"{commit}^{{commit}}").stdout.strip()
    tag_ref = f"refs/tags/{tag_name}"
    existing = git(project_dir, "rev-parse", "--verify", f"{tag_ref}^{{commit}}", check=False)
    if existing.returncode == 0:
        existing_commit = existing.stdout.strip()
        if existing_commit == resolved_commit:
            return
        raise ExperimentLogError(
            f"success tag {tag_name} already points to {existing_commit}, not {resolved_commit}"
        )
    git(project_dir, "tag", tag_name, resolved_commit)


def summary_cell(value: Any) -> str:
    text = " ".join(str(value or "").split())
    return text.replace("|", "\\|")


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def final_experiment_doc(request: dict[str, Any], branch_name: str, experiment_id: str) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "kind": "experiment_result",
        "experiment_id": experiment_id,
        "work_branch": work_branch(branch_name),
        "title": request.get("title") or request.get("short_description") or experiment_id,
        "created_at": now_iso(),
        "user_id": request.get("user_id") or user_id(),
        "source": request.get("source") or {},
        "description": request.get("description") or "",
        "code": request.get("code") or {},
        "command": request.get("command") or "",
        "status": request.get("status") or "completed",
        "success": request_successful(request),
        "key_result": request.get("key_result") or "",
        "metrics": request.get("metrics") or {},
        "artifacts": request.get("artifacts") or {},
        "notes": request.get("notes") or "",
    }


def log_experiment_once(request: dict[str, Any], project_dir: Path, branch_name: str) -> tuple[Path, str]:
    branch_name = work_branch(branch_name)
    repo = ensure_work_state(project_dir, branch_name)
    init_paths = ensure_experiment_log_files(repo, branch_name)
    log_dir = experiment_log_dir(repo)
    counter = load_counter(log_dir)
    number = int(counter.get("next_experiment_number") or 1)
    description = str(request.get("short_description") or request.get("title") or "experiment")
    experiment_id = f"E{number:04d}_{slugify(description, default='experiment')}"
    experiment_path = log_dir / "experiments" / f"{experiment_id}.yaml"
    if experiment_path.exists():
        raise ExperimentLogError(f"experiment file already exists: {experiment_path}")
    write_yaml(experiment_path, final_experiment_doc(request, branch_name, experiment_id))
    counter["next_experiment_number"] = number + 1
    write_yaml(log_dir / "COUNTER.yaml", counter)
    commit = short_commit(request)
    commit_cell = f"`{commit}`" if commit else ""
    row = (
        f"| [{experiment_id}](experiments/{experiment_id}.yaml) "
        f"| {summary_cell(request.get('user_id') or user_id())} "
        f"| {summary_cell(request.get('status') or 'completed')} "
        f"| {summary_cell(description)} "
        f"| {summary_cell(request.get('key_result') or '')} "
        f"| {commit_cell} |"
    )
    append_summary_row(log_dir / "SUMMARY.md", row)
    commit_if_changed(
        repo,
        f"experiment: log {branch_name}::{experiment_id}",
        [*init_paths, experiment_path, log_dir / "COUNTER.yaml", log_dir / "SUMMARY.md"],
    )
    return repo, qualified_experiment_ref(branch_name, experiment_id)


def retry_generated_log(
    operation: str,
    func: Callable[[dict[str, Any], Path, str], tuple[Path, str]],
    request: dict[str, Any],
    project_dir: Path,
    branch_name: str,
    after_push: Callable[[dict[str, Any], Path, str, str], None] | None = None,
) -> str:
    repo: Path | None = None
    generated_id = ""
    for attempt in range(2):
        repo, generated_id = func(request, project_dir, branch_name)
        if push(repo, work_state_branch(branch_name)):
            if after_push is not None:
                after_push(request, project_dir, branch_name, generated_id)
            return generated_id
        if attempt == 0:
            git(repo, "fetch", "origin")
            git(repo, "reset", "--hard", f"origin/{work_state_branch(branch_name)}")
    raise ExperimentLogError(f"{operation} push was rejected after retry")


def log_experiment(request: dict[str, Any], project_dir: Path, branch_name: str | None = None) -> str:
    if request.get("kind") != "experiment_result_request":
        raise ExperimentLogError("request kind must be experiment_result_request")
    try:
        active_work_branch = work_branch(branch_name or request.get("work_branch"))
        with state_lock(work_lock_path(project_dir, active_work_branch)):
            return retry_generated_log(
                "experiment",
                log_experiment_once,
                request,
                project_dir,
                active_work_branch,
                tag_successful_experiment,
            )
    except AgenticStateError as exc:
        raise ExperimentLogError(str(exc)) from exc


def experiment_path_for_id(log_dir: Path, experiment_id: str) -> Path:
    if "/" in experiment_id or "\\" in experiment_id or experiment_id in {"", ".", ".."}:
        raise ExperimentLogError(f"invalid experiment_id: {experiment_id}")
    return log_dir / "experiments" / f"{experiment_id}.yaml"


def correction_id_base(experiment_id: str) -> str:
    match = re.match(r"^(E\d+)(?:_|$)", experiment_id)
    if match:
        return match.group(1)
    return re.sub(r"[^A-Za-z0-9]+", "", experiment_id.split("_", 1)[0]) or "experiment"


def next_correction_revision(corrections: list[Any]) -> int:
    highest = 0
    for correction in corrections:
        if not isinstance(correction, dict):
            continue
        correction_id = str(correction.get("correction_id") or "")
        match = re.search(r"_R(\d+)$", correction_id)
        if match:
            highest = max(highest, int(match.group(1)))
    return highest + 1


def final_correction_doc(request: dict[str, Any], correction_id: str) -> dict[str, Any]:
    return {
        "correction_id": correction_id,
        "created_at": now_iso(),
        "user_id": request.get("user_id") or user_id(),
        "status": request.get("status") or "corrected",
        "summary": request.get("summary") or "",
        "correction": request.get("correction") or request.get("notes") or "",
        "source": request.get("source") or {},
    }


def log_correction_once(request: dict[str, Any], project_dir: Path, branch_name: str) -> tuple[Path, str]:
    experiment_ref = str(request.get("experiment_id") or "").strip()
    if not experiment_ref:
        raise ExperimentLogError("correction request requires experiment_id")
    branch_name, experiment_id = split_experiment_ref(experiment_ref, branch_name)
    repo = ensure_work_state(project_dir, branch_name)
    init_paths = ensure_experiment_log_files(repo, branch_name)
    log_dir = experiment_log_dir(repo)
    experiment_path = experiment_path_for_id(log_dir, experiment_id)
    if not experiment_path.exists():
        raise ExperimentLogError(f"experiment file does not exist: {experiment_path}")
    experiment_doc = safe_load_yaml(experiment_path)
    recorded_id = str(experiment_doc.get("experiment_id") or "").strip()
    if recorded_id and recorded_id != experiment_id:
        raise ExperimentLogError(f"experiment_id mismatch in {experiment_path}: {recorded_id}")
    corrections = experiment_doc.get("corrections")
    if corrections is None:
        corrections = []
    if not isinstance(corrections, list):
        raise ExperimentLogError(f"corrections must be a list in {experiment_path}")
    number = next_correction_revision(corrections)
    correction_id = f"{correction_id_base(experiment_id)}_R{number:03d}"
    corrections.append(final_correction_doc(request, correction_id))
    experiment_doc["corrections"] = corrections
    write_yaml(experiment_path, experiment_doc)
    row = (
        f"| [{correction_id}](experiments/{experiment_id}.yaml) "
        f"| {summary_cell(request.get('user_id') or user_id())} "
        f"| correction "
        f"| Correction for {summary_cell(experiment_id)} "
        f"| {summary_cell(request.get('summary') or request.get('correction') or '')} "
        f"|  |"
    )
    append_summary_row(log_dir / "SUMMARY.md", row)
    commit_if_changed(
        repo,
        f"experiment: correct {branch_name}::{experiment_id} ({correction_id})",
        [*init_paths, experiment_path, log_dir / "SUMMARY.md"],
    )
    return repo, qualified_experiment_ref(branch_name, correction_id)


def log_correction(request: dict[str, Any], project_dir: Path, branch_name: str | None = None) -> str:
    if request.get("kind") != "experiment_correction_request":
        raise ExperimentLogError("request kind must be experiment_correction_request")
    try:
        active_work_branch = branch_name
        experiment_ref = str(request.get("experiment_id") or "")
        if not active_work_branch and "::" in experiment_ref:
            active_work_branch = experiment_ref.split("::", 1)[0]
        active_work_branch = work_branch(active_work_branch)
        with state_lock(work_lock_path(project_dir, active_work_branch)):
            return retry_generated_log("correction", log_correction_once, request, project_dir, active_work_branch)
    except AgenticStateError as exc:
        raise ExperimentLogError(str(exc)) from exc
