"""Shared Git mechanics for built-in branch workflow tools."""

from __future__ import annotations

import datetime as dt
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import time
from typing import Any

import yaml

from ar_tool_common import ToolError, state_root


SCRIPT_DIR = Path(__file__).resolve().parent
AR_TOOL = SCRIPT_DIR.parent / "ar-tool"


def run(
    command: list[str],
    *,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
    check: bool = True,
    capture: bool = True,
    stdout_path: Path | None = None,
    stderr_path: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    stdout_target: int | Any
    stderr_target: int | Any
    stdout_handle = None
    stderr_handle = None
    try:
        if stdout_path is not None:
            stdout_path.parent.mkdir(parents=True, exist_ok=True)
            stdout_handle = stdout_path.open("w", encoding="utf-8")
            stdout_target = stdout_handle
        else:
            stdout_target = subprocess.PIPE if capture else None
        if stderr_path is not None:
            stderr_path.parent.mkdir(parents=True, exist_ok=True)
            stderr_handle = stderr_path.open("w", encoding="utf-8")
            stderr_target = stderr_handle
        else:
            stderr_target = subprocess.PIPE if capture else None

        result = subprocess.run(
            command,
            cwd=str(cwd) if cwd is not None else None,
            env=env,
            text=True,
            stdout=stdout_target,
            stderr=stderr_target,
        )
    finally:
        if stdout_handle is not None:
            stdout_handle.close()
        if stderr_handle is not None:
            stderr_handle.close()

    if check and result.returncode != 0:
        detail = ""
        if result.stderr:
            detail = result.stderr.strip()
        elif result.stdout:
            detail = result.stdout.strip()
        elif stderr_path and stderr_path.exists():
            detail = stderr_path.read_text(encoding="utf-8").strip()
        elif stdout_path and stdout_path.exists():
            detail = stdout_path.read_text(encoding="utf-8").strip()
        raise ToolError(f"{' '.join(command)} failed: {detail}")
    return result


def git(repo: Path, *args: str, env: dict[str, str] | None = None, check: bool = True) -> subprocess.CompletedProcess[str]:
    return run(["git", *args], cwd=repo, env=env, check=check)


def git_text(repo: Path, *args: str, env: dict[str, str] | None = None) -> str:
    return git(repo, *args, env=env).stdout.strip()


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def slugify(text: str, *, default: str = "item", max_len: int = 72) -> str:
    slug = re.sub(r"[^A-Za-z0-9]+", "-", text.strip().lower()).strip("-")
    slug = re.sub(r"-+", "-", slug)
    if not slug:
        slug = default
    return slug[:max_len].strip("-") or default


def safe_load_yaml(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ToolError(f"{path} must contain a YAML mapping")
    return data


def write_yaml(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=False), encoding="utf-8")


def resolve_project_dir(request: dict[str, Any]) -> Path:
    raw = request.get("project_dir") or "."
    project_dir = Path(str(raw)).expanduser().resolve()
    inside = git_text(project_dir, "rev-parse", "--is-inside-work-tree")
    if inside != "true":
        raise ToolError(f"not inside a Git worktree: {project_dir}")
    return project_dir


def current_branch(project_dir: Path) -> str:
    branch = git_text(project_dir, "branch", "--show-current")
    if not branch:
        raise ToolError("current worktree is detached; branch commits require a named branch")
    return branch


def current_commit(project_dir: Path) -> str:
    return git_text(project_dir, "rev-parse", "HEAD")


def validate_topic_branch(branch: str, topic: str | None) -> str:
    topic_value = slugify(
        topic
        or os.environ.get("AR_AGENT_BRANCH_ID", "")
        or os.environ.get("AR_AGENT_TOPIC", ""),
        default="",
    )
    if not topic_value:
        match = re.match(r"^agent/([^/]+)(?:/.*)?$", branch)
        if match:
            topic_value = slugify(match.group(1), default="")
    if not topic_value:
        raise ToolError("branch snapshot request needs branch_log, AR_AGENT_BRANCH_ID, or an agent/* branch")
    prefix = f"agent/{topic_value}"
    if branch != prefix and not branch.startswith(f"{prefix}/"):
        raise ToolError(f"current branch '{branch}' does not match agent branch '{prefix}'")
    return topic_value


def validate_paths(paths: Any) -> list[str]:
    if not isinstance(paths, list) or not paths:
        raise ToolError("branch snapshot request requires non-empty paths")
    result: list[str] = []
    for raw in paths:
        path = str(raw).strip()
        if not path:
            raise ToolError("empty path in branch snapshot request")
        normalized = Path(path)
        if normalized.is_absolute() or ".." in normalized.parts or ".git" in normalized.parts:
            raise ToolError(f"unsafe path in branch snapshot request: {path}")
        if path in {".", "./", "*", ":/", ":."}:
            raise ToolError(f"overly broad path in branch snapshot request: {path}")
        if any(char in path for char in "*?[]"):
            raise ToolError(f"glob patterns are not allowed in branch snapshot request paths: {path}")
        result.append(path)
    return result


def request_checks(request: dict[str, Any]) -> list[str]:
    checks = request.get("checks") or []
    if not isinstance(checks, list):
        raise ToolError("checks must be a list of shell commands")
    return [str(item) for item in checks]


def request_commit_message(request: dict[str, Any]) -> str:
    message = str(request.get("commit_message") or "").strip()
    if not message:
        raise ToolError("branch snapshot request requires commit_message")
    return message


def snapshot_root(snapshot_id: str) -> Path:
    return state_root() / "commit-snapshots" / snapshot_id


def status_path(snapshot_dir: Path) -> Path:
    return snapshot_dir / "status.yaml"


def metadata_path(snapshot_dir: Path) -> Path:
    return snapshot_dir / "metadata.yaml"


def update_status(snapshot_dir: Path, **updates: Any) -> None:
    path = status_path(snapshot_dir)
    data = safe_load_yaml(path) if path.exists() else {}
    data.update(updates)
    data["updated_at"] = now_iso()
    write_yaml(path, data)


def create_snapshot(request: dict[str, Any]) -> dict[str, Any]:
    project_dir = resolve_project_dir(request)
    branch = current_branch(project_dir)
    topic = validate_topic_branch(branch, str(request.get("topic") or ""))
    base_commit = current_commit(project_dir)
    paths = validate_paths(request.get("paths"))
    checks = request_checks(request)
    commit_message = request_commit_message(request)

    snapshot_id = f"{int(time.time())}-{os.getpid()}-{slugify(topic)}"
    root = snapshot_root(snapshot_id)
    root.mkdir(parents=True, exist_ok=False)
    patch_path = root / "snapshot.patch"
    name_status_path = root / "name-status.txt"
    temp_index = root / "index"
    env = os.environ.copy()
    env["GIT_INDEX_FILE"] = str(temp_index)

    git(project_dir, "read-tree", "HEAD", env=env)
    git(project_dir, "add", "-A", "--", *paths, env=env)
    run(
        ["git", "diff", "--cached", "--binary", "--", *paths],
        cwd=project_dir,
        env=env,
        stdout_path=patch_path,
    )
    name_status = run(
        ["git", "diff", "--cached", "--name-status", "--", *paths],
        cwd=project_dir,
        env=env,
    ).stdout
    name_status_path.write_text(name_status, encoding="utf-8")
    if not name_status.strip():
        raise ToolError("requested paths have no changes to snapshot")

    after_commit = request.get("after_commit") if isinstance(request.get("after_commit"), dict) else {}
    metadata = {
        "snapshot_id": snapshot_id,
        "created_at": now_iso(),
        "project_dir": str(project_dir),
        "branch": branch,
        "topic": topic,
        "base_commit": base_commit,
        "paths": paths,
        "commit_message": commit_message,
        "checks": checks,
        "after_commit": after_commit,
        "patch_path": str(patch_path),
        "name_status_path": str(name_status_path),
    }
    write_yaml(metadata_path(root), metadata)
    status = {
        "snapshot_id": snapshot_id,
        "state": "snapshotted",
        "created_at": metadata["created_at"],
        "updated_at": metadata["created_at"],
        "snapshot_dir": str(root),
        "branch": branch,
        "base_commit": base_commit,
        "paths": paths,
        "name_status_path": str(name_status_path),
        "name_status": name_status.splitlines(),
    }
    write_yaml(status_path(root), status)
    return {
        "snapshot_id": snapshot_id,
        "snapshot_dir": str(root),
        "status_path": str(status_path(root)),
        "branch": branch,
        "base_commit": base_commit,
        "paths": paths,
        "name_status_path": str(name_status_path),
        "name_status": name_status.splitlines(),
    }


def run_checks(worktree: Path, checks: list[str], log_path: Path) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    with log_path.open("w", encoding="utf-8") as log:
        for command in checks:
            started = now_iso()
            log.write(f"$ {command}\n")
            result = subprocess.run(
                command,
                cwd=worktree,
                shell=True,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
            )
            output = result.stdout or ""
            log.write(output)
            if output and not output.endswith("\n"):
                log.write("\n")
            log.write(f"[exit {result.returncode}]\n\n")
            results.append(
                {
                    "command": command,
                    "returncode": result.returncode,
                    "started_at": started,
                    "finished_at": now_iso(),
                }
            )
            if result.returncode != 0:
                raise ToolError(f"check failed: {command}; see {log_path}")
    return results


def prepare_after_commit_experiment(metadata: dict[str, Any], commit_hash: str) -> dict[str, Any] | None:
    after_commit = metadata.get("after_commit")
    if not isinstance(after_commit, dict):
        return None
    request = after_commit.get("experiment_log")
    if not isinstance(request, dict):
        return None
    finalized = dict(request)
    finalized.setdefault("topic", metadata.get("topic"))
    code = finalized.get("code")
    if not isinstance(code, dict):
        code = {}
    code.setdefault("branch", metadata.get("branch"))
    code.setdefault("commit", commit_hash)
    finalized["code"] = code
    finalized.setdefault("project_dir", metadata.get("project_dir"))
    return finalized


def log_after_commit_experiment(
    snapshot_dir: Path,
    metadata: dict[str, Any],
    request: dict[str, Any] | None,
) -> dict[str, Any]:
    if not request:
        return {}

    request_path = snapshot_dir / "experiment-log-request.yaml"
    write_yaml(request_path, request)
    ar_tool = Path(os.environ.get("AR_TOOL_CLI") or AR_TOOL).expanduser()
    command = [str(ar_tool), "run", "experiment-log"]
    log_path = snapshot_dir / "experiment-log.log"
    result = subprocess.run(
        command,
        input=yaml.safe_dump(request, sort_keys=False, allow_unicode=False),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    output = result.stdout or ""
    log_path.write_text(output, encoding="utf-8")
    if result.returncode == 0:
        output_lines = [line for line in output.splitlines() if line.strip()]
        last_line = output_lines[-1] if output_lines else ""
        try:
            parsed = json.loads(last_line)
            experiment_id = str(parsed.get("experiment_id") or "").strip()
        except json.JSONDecodeError:
            experiment_id = last_line
        return {
            "experiment_log_state": "logged",
            "experiment_log_id": experiment_id,
            "experiment_log_path": str(log_path),
            "experiment_log_request_path": str(request_path),
            "experiment_log_command": command,
        }
    return {
        "experiment_log_state": "failed",
        "experiment_log_error": output.strip() or f"{ar_tool} exited with status {result.returncode}",
        "experiment_log_path": str(log_path),
        "experiment_log_request_path": str(request_path),
        "experiment_log_command": command,
    }


def commit_snapshot_foreground(snapshot_dir: Path) -> dict[str, Any]:
    metadata = safe_load_yaml(metadata_path(snapshot_dir))
    project_dir = Path(str(metadata["project_dir"]))
    branch = str(metadata["branch"])
    base_commit = str(metadata["base_commit"])
    patch_path = Path(str(metadata["patch_path"]))
    paths = [str(item) for item in metadata.get("paths", [])]
    checks = [str(item) for item in metadata.get("checks", [])]
    commit_message = str(metadata["commit_message"])
    worktree = state_root() / "commit-worktrees" / str(metadata["snapshot_id"]) / slugify(branch)
    check_log = snapshot_dir / "checks.log"

    update_status(snapshot_dir, state="running", started_at=now_iso(), worktree=str(worktree))
    if worktree.exists():
        shutil.rmtree(worktree)
    worktree.parent.mkdir(parents=True, exist_ok=True)

    try:
        git(project_dir, "worktree", "add", "--detach", str(worktree), base_commit)
        git(worktree, "apply", "--index", "--binary", str(patch_path))
        check_results = run_checks(worktree, checks, check_log) if checks else []
        stat = git_text(worktree, "diff", "--cached", "--stat")
        git(worktree, "commit", "-m", commit_message)
        new_commit = git_text(worktree, "rev-parse", "HEAD")
        ref = f"refs/heads/{branch}"
        git(project_dir, "update-ref", ref, new_commit, base_commit)
        if paths:
            git(project_dir, "reset", "-q", "HEAD", "--", *paths, check=False)
        experiment_request = prepare_after_commit_experiment(metadata, new_commit)
        experiment_log_result = log_after_commit_experiment(snapshot_dir, metadata, experiment_request)
        result = {
            "snapshot_id": metadata["snapshot_id"],
            "state": "committed",
            "branch": branch,
            "base_commit": base_commit,
            "commit": new_commit,
            "worktree": str(worktree),
            "check_log": str(check_log),
            "checks": check_results,
            "diff_stat": stat,
            "experiment_request_path": (
                experiment_log_result.get("experiment_log_request_path") if experiment_log_result else None
            ),
            "finished_at": now_iso(),
        }
        result.update(experiment_log_result)
        update_status(snapshot_dir, **result)
        return result
    except Exception as exc:
        update_status(snapshot_dir, state="failed", error=str(exc), failed_at=now_iso(), worktree=str(worktree))
        raise


def start_background_commit(snapshot_dir: Path, worker_command: list[str]) -> dict[str, Any]:
    log_path = snapshot_dir / "commit-background.log"
    with log_path.open("a", encoding="utf-8") as log:
        process = subprocess.Popen(worker_command, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    update_status(snapshot_dir, state="queued", pid=process.pid, background_log=str(log_path))
    return {
        "snapshot_id": safe_load_yaml(metadata_path(snapshot_dir)).get("snapshot_id"),
        "state": "queued",
        "pid": process.pid,
        "status_path": str(status_path(snapshot_dir)),
        "background_log": str(log_path),
    }


def show_status(snapshot_dir: Path) -> dict[str, Any]:
    return safe_load_yaml(status_path(snapshot_dir))
