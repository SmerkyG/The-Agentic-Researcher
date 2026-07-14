"""Shared Git mechanics for built-in branch workflow commands."""

from __future__ import annotations

import datetime as dt
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import time
from typing import Any

import yaml

from command_common import CommandError, bool_from, runtime_root


SCRIPT_DIR = Path(__file__).resolve().parent


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
        raise CommandError(f"{' '.join(command)} failed: {detail}")
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
        raise CommandError(f"{path} must contain a YAML mapping")
    return data


def write_yaml(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=False), encoding="utf-8")


def path_is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
    except ValueError:
        return False
    return True


def resolve_project_dir(request: dict[str, Any]) -> Path:
    raw = request.get("project_dir") or "."
    project_dir = Path(str(raw)).expanduser().resolve()
    inside = git_text(project_dir, "rev-parse", "--is-inside-work-tree")
    if inside != "true":
        raise CommandError(f"not inside a Git worktree: {project_dir}")
    return project_dir


def current_branch(project_dir: Path) -> str:
    branch = git_text(project_dir, "branch", "--show-current")
    if not branch:
        raise CommandError("current worktree is detached; branch commits require a named branch")
    return branch


def current_commit(project_dir: Path) -> str:
    return git_text(project_dir, "rev-parse", "HEAD")


def work_branch_from_child(branch: str) -> str:
    marker = "/exp/"
    if marker in branch:
        return branch.split(marker, 1)[0]
    return branch


def validate_work_branch(branch: str, requested: str | None) -> str:
    work_branch = str(requested or os.environ.get("AR_WORK_BRANCH") or "").strip()
    if not work_branch:
        work_branch = work_branch_from_child(branch)
    if not work_branch:
        raise CommandError("branch snapshot request needs work_branch, AR_WORK_BRANCH, or a named Git branch")
    if branch != work_branch and not branch.startswith(f"{work_branch}/exp/"):
        raise CommandError(f"current branch '{branch}' does not match work branch '{work_branch}'")
    return work_branch


def validate_paths(paths: Any) -> list[str]:
    if not isinstance(paths, list) or not paths:
        raise CommandError("branch snapshot request requires non-empty paths")
    result: list[str] = []
    for raw in paths:
        path = str(raw).strip()
        if not path:
            raise CommandError("empty path in branch snapshot request")
        normalized = Path(path)
        if normalized.is_absolute() or ".." in normalized.parts or ".git" in normalized.parts:
            raise CommandError(f"unsafe path in branch snapshot request: {path}")
        if path in {".", "./", "*", ":/", ":."}:
            raise CommandError(f"overly broad path in branch snapshot request: {path}")
        if any(char in path for char in "*?[]"):
            raise CommandError(f"glob patterns are not allowed in branch snapshot request paths: {path}")
        result.append(path)
    return result


def request_checks(request: dict[str, Any]) -> list[str]:
    checks = request.get("checks") or []
    if not isinstance(checks, list):
        raise CommandError("checks must be a list of shell commands")
    return [str(item) for item in checks]


def request_check_timeout_seconds(request: dict[str, Any]) -> int | None:
    value = request.get("check_timeout_seconds")
    if value is None or value == "":
        value = os.environ.get("AR_BRANCH_CHECK_TIMEOUT_SECONDS")
    if value is None or value == "":
        return None
    try:
        seconds = int(value)
    except (TypeError, ValueError) as exc:
        raise CommandError("check_timeout_seconds must be a positive integer") from exc
    if seconds <= 0:
        raise CommandError("check_timeout_seconds must be a positive integer")
    return seconds


def request_commit_message(request: dict[str, Any]) -> str:
    message = str(request.get("commit_message") or "").strip()
    if not message:
        raise CommandError("branch snapshot request requires commit_message")
    return message


def snapshot_root(snapshot_id: str, project_dir: Path) -> Path:
    return runtime_root(project_dir) / "commit-snapshots" / snapshot_id


def commit_worktree_root(project_dir: Path | None = None, snapshot_dir: Path | None = None) -> Path:
    if project_dir is not None:
        return runtime_root(project_dir) / "commit-worktrees"
    if snapshot_dir is not None:
        return snapshot_dir.parents[1] / "commit-worktrees"
    return runtime_root() / "commit-worktrees"


def commit_worktree_root_for(
    metadata: dict[str, Any],
    project_dir: Path | None = None,
    snapshot_dir: Path | None = None,
) -> Path:
    if metadata.get("runtime_root"):
        return Path(str(metadata["runtime_root"])) / "commit-worktrees"
    return commit_worktree_root(project_dir=project_dir, snapshot_dir=snapshot_dir)


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
    work_branch = validate_work_branch(branch, str(request.get("work_branch") or ""))
    base_commit = current_commit(project_dir)
    paths = validate_paths(request.get("paths"))
    checks = request_checks(request)
    check_timeout_seconds = request_check_timeout_seconds(request)
    commit_message = request_commit_message(request)

    snapshot_id = f"{int(time.time())}-{os.getpid()}-{slugify(work_branch)}"
    root = snapshot_root(snapshot_id, project_dir)
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
        raise CommandError("requested paths have no changes to snapshot")

    after_commit = request.get("after_commit") if isinstance(request.get("after_commit"), dict) else {}
    metadata = {
        "snapshot_id": snapshot_id,
        "created_at": now_iso(),
        "project_dir": str(project_dir),
        "runtime_root": str(runtime_root(project_dir)),
        "branch": branch,
        "work_branch": work_branch,
        "base_commit": base_commit,
        "paths": paths,
        "commit_message": commit_message,
        "checks": checks,
        "check_timeout_seconds": check_timeout_seconds,
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


def terminate_process_group(process: subprocess.Popen[str], log: Any) -> None:
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    except Exception as exc:  # pragma: no cover - platform-specific fallback
        log.write(f"[warning] failed to terminate process group {process.pid}: {exc}\n")
        process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            return
        except Exception as exc:  # pragma: no cover - platform-specific fallback
            log.write(f"[warning] failed to kill process group {process.pid}: {exc}\n")
            process.kill()
        process.wait(timeout=5)


def run_checks(
    worktree: Path,
    checks: list[str],
    log_path: Path,
    *,
    snapshot_dir: Path,
    timeout_seconds: int | None = None,
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    with log_path.open("w", encoding="utf-8", buffering=1) as log:
        for index, command in enumerate(checks, start=1):
            started = now_iso()
            update_status(
                snapshot_dir,
                state="running",
                check_log=str(log_path),
                current_check=command,
                current_check_index=index,
                check_count=len(checks),
                current_check_started_at=started,
            )
            log.write(f"$ {command}\n")
            process = subprocess.Popen(
                command,
                cwd=worktree,
                shell=True,
                text=True,
                stdout=log,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
            timed_out = False
            try:
                returncode = process.wait(timeout=timeout_seconds)
            except subprocess.TimeoutExpired:
                timed_out = True
                log.write(f"\n[timeout after {timeout_seconds} seconds]\n")
                terminate_process_group(process, log)
                returncode = process.returncode if process.returncode is not None else -signal.SIGTERM
            log.write(f"[exit {returncode}]\n\n")
            results.append(
                {
                    "command": command,
                    "returncode": returncode,
                    "started_at": started,
                    "finished_at": now_iso(),
                    "timed_out": timed_out,
                }
            )
            update_status(
                snapshot_dir,
                state="running",
                check_log=str(log_path),
                checks=results,
                last_check=command,
                last_check_returncode=returncode,
                current_check=None,
                current_check_index=None,
                current_check_started_at=None,
            )
            if timed_out:
                raise CommandError(f"check timed out after {timeout_seconds} seconds: {command}; see {log_path}")
            if returncode != 0:
                raise CommandError(f"check failed: {command}; see {log_path}")
    return results


def require_git_commit_identity(repo: Path) -> str:
    missing: list[str] = []
    details: list[str] = []
    identities: list[str] = []
    for var_name in ("GIT_AUTHOR_IDENT", "GIT_COMMITTER_IDENT"):
        result = git(repo, "var", var_name, check=False)
        if result.returncode == 0:
            identities.append(result.stdout.strip())
            continue
        missing.append(var_name)
        detail = (result.stderr or result.stdout or "").strip()
        if detail:
            details.append(detail)
    if not missing:
        return "\n".join(identities)

    env_name = os.environ.get("AR_GIT_NAME") or os.environ.get("AR_NOTES_GIT_NAME")
    env_email = os.environ.get("AR_GIT_EMAIL") or os.environ.get("AR_NOTES_GIT_EMAIL")
    if env_name and env_email:
        git(repo, "config", "user.name", env_name)
        git(repo, "config", "user.email", env_email)
        return require_git_commit_identity(repo)

    guidance = (
        "Git commit identity is not configured for this repository. "
        "Set a repo-local identity before running branch-commit, for example: "
        "git config user.name \"Your Name\" && "
        "git config user.email \"you@example.com\""
    )
    if details:
        guidance = f"{guidance}\n\nGit said:\n" + "\n".join(details)
    raise CommandError(guidance)


def prepare_after_commit_experiment(metadata: dict[str, Any], commit_hash: str) -> dict[str, Any] | None:
    after_commit = metadata.get("after_commit")
    if not isinstance(after_commit, dict):
        return None
    request = after_commit.get("experiment_log")
    if not isinstance(request, dict):
        return None
    finalized = dict(request)
    finalized.setdefault("work_branch", metadata.get("work_branch"))
    code = finalized.get("code")
    if not isinstance(code, dict):
        code = {}
    if not code.get("branch"):
        code["branch"] = metadata.get("branch")
    if not code.get("commit"):
        code["commit"] = commit_hash
    finalized["code"] = code
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
    command = ["experiment-log", "append", "--project-dir", str(metadata["project_dir"])]
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
        "experiment_log_error": output.strip() or f"experiment-log exited with status {result.returncode}",
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
    timeout_raw = metadata.get("check_timeout_seconds")
    check_timeout_seconds = int(timeout_raw) if timeout_raw else None
    commit_message = str(metadata["commit_message"])
    worktree_root = commit_worktree_root_for(metadata, project_dir=project_dir, snapshot_dir=snapshot_dir)
    worktree = worktree_root / str(metadata["snapshot_id"]) / slugify(branch)
    check_log = snapshot_dir / "checks.log"

    update_status(
        snapshot_dir,
        state="running",
        pid=os.getpid(),
        started_at=now_iso(),
        worktree=str(worktree),
        check_log=str(check_log),
        check_count=len(checks),
    )
    if worktree.exists():
        shutil.rmtree(worktree)
    worktree.parent.mkdir(parents=True, exist_ok=True)

    try:
        require_git_commit_identity(project_dir)
        git(project_dir, "worktree", "add", "--detach", str(worktree), base_commit)
        git(worktree, "apply", "--index", "--binary", str(patch_path))
        check_results = (
            run_checks(
                worktree,
                checks,
                check_log,
                snapshot_dir=snapshot_dir,
                timeout_seconds=check_timeout_seconds,
            )
            if checks
            else []
        )
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
    update_status(snapshot_dir, state="queued", background_log=str(log_path))
    with log_path.open("a", encoding="utf-8") as log:
        process = subprocess.Popen(worker_command, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    update_status(snapshot_dir, pid=process.pid, background_log=str(log_path))
    return {
        "snapshot_id": safe_load_yaml(metadata_path(snapshot_dir)).get("snapshot_id"),
        "state": "queued",
        "pid": process.pid,
        "status_path": str(status_path(snapshot_dir)),
        "background_log": str(log_path),
    }


def show_status(snapshot_dir: Path) -> dict[str, Any]:
    status = safe_load_yaml(status_path(snapshot_dir))
    pid = status.get("pid")
    if isinstance(pid, int) and pid > 0:
        try:
            os.kill(pid, 0)
            status["pid_alive"] = True
        except ProcessLookupError:
            status["pid_alive"] = False
        except PermissionError:
            status["pid_alive"] = True
    return status


def parse_datetime(value: Any) -> dt.datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = dt.datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed.astimezone(dt.timezone.utc)


def snapshot_timestamp(snapshot_dir: Path, status: dict[str, Any], metadata: dict[str, Any]) -> dt.datetime:
    for key in ("finished_at", "failed_at", "updated_at", "created_at"):
        parsed = parse_datetime(status.get(key) or metadata.get(key))
        if parsed is not None:
            return parsed
    return dt.datetime.fromtimestamp(snapshot_dir.stat().st_mtime, tz=dt.timezone.utc)


def requested_states(request: dict[str, Any]) -> set[str]:
    raw = request.get("states")
    if raw is None:
        return {"committed", "failed", "snapshotted"}
    if not isinstance(raw, list) or not raw:
        raise CommandError("states must be a non-empty list")
    states = {str(item).strip() for item in raw if str(item).strip()}
    if not states:
        raise CommandError("states must include at least one non-empty value")
    return states


def requested_snapshot_dirs(request: dict[str, Any]) -> list[Path] | None:
    raw = request.get("snapshot_dirs")
    if raw is None:
        raw_single = request.get("snapshot_dir")
        if raw_single is None:
            return None
        raw = [raw_single]
    if not isinstance(raw, list) or not raw:
        raise CommandError("snapshot_dirs must be a non-empty list")
    return [Path(str(item)).expanduser().resolve() for item in raw]


def snapshot_dirs_for_cleanup(request: dict[str, Any]) -> list[Path]:
    explicit = requested_snapshot_dirs(request)
    if explicit is not None:
        return explicit
    project_filter = project_filter_path(request)
    root = runtime_root(project_filter) / "commit-snapshots"
    if not root.exists():
        return []
    return sorted(path for path in root.iterdir() if path.is_dir())


def snapshot_allowed_root(metadata: dict[str, Any], project_dir: Path | None) -> Path:
    if metadata.get("runtime_root"):
        return Path(str(metadata["runtime_root"])) / "commit-snapshots"
    return runtime_root(project_dir) / "commit-snapshots"


def non_negative_int_request(request: dict[str, Any], key: str, default: int) -> int:
    value = request.get(key, default)
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise CommandError(f"{key} must be a non-negative integer") from exc
    if number < 0:
        raise CommandError(f"{key} must be a non-negative integer")
    return number


def project_filter_path(request: dict[str, Any]) -> Path | None:
    value = request.get("project_dir")
    if value is None or str(value).strip() == "":
        return None
    return Path(str(value)).expanduser().resolve()


def pid_alive(pid: Any) -> bool:
    if not isinstance(pid, int) or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def load_snapshot_files(snapshot_dir: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    metadata_file = metadata_path(snapshot_dir)
    status_file = status_path(snapshot_dir)
    metadata = safe_load_yaml(metadata_file) if metadata_file.exists() else {}
    status = safe_load_yaml(status_file) if status_file.exists() else {}
    return metadata, status


def compact_worktree_parents(worktree: Path, root: Path) -> None:
    root = root.resolve()
    current = worktree.parent
    for _ in range(2):
        try:
            current.resolve().relative_to(root)
        except ValueError:
            return
        if current == root:
            return
        try:
            current.rmdir()
        except OSError:
            return
        current = current.parent


def remove_registered_worktree(project_dir: Path | None, worktree: Path, worktree_root: Path) -> list[str]:
    warnings: list[str] = []
    if not path_is_relative_to(worktree, worktree_root):
        raise CommandError(f"refusing to remove worktree outside commit-worktrees: {worktree}")
    if project_dir is not None and project_dir.exists():
        result = git(project_dir, "worktree", "remove", "--force", str(worktree), check=False)
        if result.returncode == 0:
            git(project_dir, "worktree", "prune", check=False)
            compact_worktree_parents(worktree, worktree_root)
            return warnings
        detail = (result.stderr or result.stdout or "").strip()
        warnings.append(f"git worktree remove failed for {worktree}: {detail}")

    common_dir = None
    if worktree.exists():
        result = git(worktree, "rev-parse", "--git-common-dir", check=False)
        if result.returncode == 0 and result.stdout.strip():
            common_dir = Path(result.stdout.strip()).expanduser()
            if not common_dir.is_absolute():
                common_dir = (worktree / common_dir).resolve()

    if worktree.exists():
        shutil.rmtree(worktree)
    if common_dir is not None and common_dir.exists():
        run(["git", "--git-dir", str(common_dir), "worktree", "prune"], check=False)
    compact_worktree_parents(worktree, worktree_root)
    return warnings


def cleanup_commit_artifacts(request: dict[str, Any]) -> dict[str, Any]:
    dry_run = bool_from(request.get("dry_run"), default=True)
    states = requested_states(request)
    older_than_days = non_negative_int_request(request, "older_than_days", 7)
    cutoff = None
    if older_than_days > 0:
        cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=older_than_days)
    project_filter = project_filter_path(request)
    include_active = bool_from(request.get("include_active"), default=False)

    removed: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    planned: list[dict[str, Any]] = []

    for snapshot_dir in snapshot_dirs_for_cleanup(request):
        base_entry: dict[str, Any] = {"snapshot_dir": str(snapshot_dir)}
        if not snapshot_dir.exists():
            skipped.append({**base_entry, "reason": "missing"})
            continue

        metadata, status = load_snapshot_files(snapshot_dir)
        snapshot_id = str(metadata.get("snapshot_id") or status.get("snapshot_id") or snapshot_dir.name)
        state = str(status.get("state") or "unknown")
        project_dir = Path(str(metadata["project_dir"])).expanduser().resolve() if metadata.get("project_dir") else None
        allowed_root = snapshot_allowed_root(metadata, project_dir)
        if not path_is_relative_to(snapshot_dir, allowed_root):
            skipped.append({**base_entry, "reason": "outside commit-snapshots"})
            continue
        timestamp = snapshot_timestamp(snapshot_dir, status, metadata)
        worktree_raw = status.get("worktree")
        worktree = Path(str(worktree_raw)).expanduser().resolve() if worktree_raw else None
        worktree_root = commit_worktree_root_for(metadata, project_dir=project_dir, snapshot_dir=snapshot_dir)
        entry = {
            **base_entry,
            "snapshot_id": snapshot_id,
            "state": state,
            "updated_at": timestamp.isoformat(timespec="seconds"),
            "project_dir": str(project_dir) if project_dir is not None else None,
            "worktree": str(worktree) if worktree is not None else None,
        }

        if project_filter is not None and project_dir != project_filter:
            skipped.append({**entry, "reason": "project filter"})
            continue
        if state not in states:
            skipped.append({**entry, "reason": "state not selected"})
            continue
        if cutoff is not None and timestamp > cutoff:
            skipped.append({**entry, "reason": "younger than retention"})
            continue
        if state in {"queued", "running"} and not include_active:
            skipped.append({**entry, "reason": "active state"})
            continue
        if state in {"queued", "running"} and pid_alive(status.get("pid")):
            skipped.append({**entry, "reason": "pid alive"})
            continue

        if dry_run:
            planned.append(entry)
            continue

        warnings: list[str] = []
        if worktree is not None:
            warnings = remove_registered_worktree(project_dir, worktree, worktree_root)
        shutil.rmtree(snapshot_dir)
        removed.append({**entry, "warnings": warnings})

    return {
        "dry_run": dry_run,
        "runtime_root": str(runtime_root(project_filter)),
        "older_than_days": older_than_days,
        "selected_states": sorted(states),
        "planned": planned,
        "removed": removed,
        "skipped": skipped,
        "planned_count": len(planned),
        "removed_count": len(removed),
        "skipped_count": len(skipped),
    }
