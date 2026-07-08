"""Shared Git-backed Agentic Team state mechanics.

This module owns local state worktree management, work-branch identity, locking,
and ordinary Git synchronization. Capabilities use it as substrate; they own
the files and schemas they place in those state worktrees.
"""

from __future__ import annotations

from contextlib import contextmanager
import os
from pathlib import Path
import re
import shutil
import subprocess
import threading
import time
from typing import Any, Callable

import yaml

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows fallback
    fcntl = None  # type: ignore[assignment]


class AgenticStateError(RuntimeError):
    pass


def run(
    command: list[str],
    *,
    cwd: Path | None = None,
    check: bool = True,
    capture: bool = True,
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        command,
        cwd=str(cwd) if cwd is not None else None,
        text=True,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.PIPE if capture else None,
    )
    if check and result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip()
        raise AgenticStateError(f"{' '.join(command)} failed: {detail}")
    return result


def git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return run(["git", *args], cwd=repo, check=check)


def env_bool(name: str, default: bool = True) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() not in {"0", "false", "no", "off"}


def state_root() -> Path:
    return Path(os.environ.get("AR_STATE_ROOT", "~/.cache/agentic-team")).expanduser()


def explicit_workspace_root() -> Path | None:
    value = os.environ.get("AR_WORKSPACE_ROOT")
    if not value:
        return None
    return Path(value).expanduser()


def explicit_runtime_root() -> Path | None:
    value = os.environ.get("AR_RUNTIME_ROOT")
    if not value:
        return None
    return Path(value).expanduser()


def state_branch() -> str:
    return os.environ.get("AR_PROJECT_STATE_BRANCH", "agentic/project-state")


def work_state_branch(branch: str) -> str:
    return f"agentic/work-state/{work_branch(branch)}"


def agent_type(value: str | None = None) -> str:
    return value or os.environ.get("AR_MAIN_AGENT") or "research-coordinator"


def user_id(value: str | None = None) -> str:
    return value or os.environ.get("AR_USER_ID") or os.environ.get("USER") or "user"


def work_branch(value: str | None = None) -> str:
    raw = value or os.environ.get("AR_WORK_BRANCH") or ""
    branch = raw.strip()
    if branch.startswith("refs/heads/"):
        branch = branch.removeprefix("refs/heads/")
    if not branch:
        raise AgenticStateError("work branch is required; launch from a Git branch or pass --work-branch")
    if branch.startswith("/") or branch.endswith("/") or branch in {".", ".."} or ".." in branch.split("/"):
        raise AgenticStateError(f"invalid work branch: {branch}")
    return branch


def work_branch_id(value: str | None = None) -> str:
    return slugify(work_branch(value), default="branch")


def work_name(value: str | None = None) -> str:
    branch = work_branch(value)
    return slugify(Path(branch).name, default=work_branch_id(branch))


def safe_load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data, dict):
        return {}
    return data


def parse_yaml_mapping(text: str, source: str) -> dict[str, Any]:
    data = yaml.safe_load(text) or {}
    if not isinstance(data, dict):
        raise AgenticStateError(f"{source} must contain a YAML mapping")
    return data


def request_from_args(args: Any) -> dict[str, Any]:
    cached = getattr(args, "_request_data", None)
    if isinstance(cached, dict):
        return cached
    request_path = getattr(args, "request", None)
    if not request_path:
        return {}
    if request_path == "-":
        text = getattr(args, "_request_text", "")
        request = parse_yaml_mapping(text, "stdin request")
    else:
        request = safe_load_yaml(Path(request_path))
    args._request_data = request
    return request


def write_yaml(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        yaml.safe_dump(data, handle, sort_keys=False, allow_unicode=False)


def slugify(text: str, *, default: str = "item", max_len: int = 72) -> str:
    slug = re.sub(r"[^A-Za-z0-9]+", "-", text.strip().lower()).strip("-")
    slug = re.sub(r"-+", "-", slug)
    if not slug:
        slug = default
    return slug[:max_len].rstrip("-") or default


def fallback_workspace_name(project_dir: Path) -> str:
    expanded = project_dir.expanduser()
    if expanded.name == "code" and expanded.parent.parent.name.endswith("-at"):
        at_root = expanded.parent.parent
        project_link = at_root / "project"
        if project_link.exists() or project_link.is_symlink():
            try:
                return slugify(project_link.resolve().name, default="project")
            except OSError:
                pass
        return slugify(at_root.name.removesuffix("-at"), default="project")

    try:
        return slugify(expanded.resolve().name, default="project")
    except OSError:
        return slugify(expanded.name, default="project")


def is_remote_repo_spec(value: str) -> bool:
    value = value.strip()
    if re.match(r"^[A-Za-z][A-Za-z0-9+.-]*://", value):
        return True
    if re.match(r"^[A-Za-z]:[\\/]", value):
        return False
    return re.match(r"^(?:[^@/:]+@)?[^/:]+:.+$", value) is not None


def workspace_name(project_dir: Path) -> str:
    return fallback_workspace_name(project_dir)


def workspace_root(project_dir: Path) -> Path:
    configured = explicit_workspace_root()
    if configured is not None:
        return configured

    expanded = project_dir.expanduser()
    if expanded.name == "code" and expanded.parent.parent.name.endswith("-at"):
        return expanded.parent.parent.resolve()

    resolved = expanded.resolve()
    if resolved.name == "code" and resolved.parent.parent.name.endswith("-at"):
        return resolved.parent.parent

    return resolved.parent / f"{workspace_name(project_dir)}-at"


def runtime_root(project_dir: Path | None = None) -> Path:
    configured = explicit_runtime_root()
    if configured is not None:
        return configured

    configured_workspace = explicit_workspace_root()
    if configured_workspace is not None:
        return configured_workspace / ".runtime"

    if project_dir is not None:
        return workspace_root(project_dir) / ".runtime"

    raise AgenticStateError("runtime root requires AR_RUNTIME_ROOT, AR_WORKSPACE_ROOT, or project_dir")


def org_checkout_path() -> Path:
    return state_root() / "repos" / "org-agentic-notes"


def project_state_path(project_dir: Path) -> Path:
    return workspace_root(project_dir) / "project-state"


def work_state_path(
    project_dir: Path,
    branch: str,
) -> Path:
    return workspace_root(project_dir) / work_name(branch) / "state"


def lock_file_for(
    name: str,
    project_dir: Path | None = None,
) -> Path:
    root = state_root() if name == "org-agentic-notes" else runtime_root(project_dir)
    return root / "locks" / f"{slugify(name, default='state')}.lock"


def org_lock_path() -> Path:
    return lock_file_for("org-agentic-notes")


def project_lock_path(project_dir: Path) -> Path:
    return lock_file_for("project", project_dir)


def work_lock_path(
    project_dir: Path,
    work_branch_value: str | None,
) -> Path:
    return lock_file_for(f"work-{work_branch_id(work_branch_value)}", project_dir)


@contextmanager
def state_lock(lock_path: Path):
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    if fcntl is not None:
        with lock_path.open("w", encoding="utf-8") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        return

    lock_dir = lock_path.with_suffix(lock_path.suffix + ".dir")
    while True:  # pragma: no cover - exercised only without fcntl
        try:
            lock_dir.mkdir()
            break
        except FileExistsError:
            time.sleep(0.1)
    try:
        yield
    finally:
        shutil.rmtree(lock_dir, ignore_errors=True)


@contextmanager
def nonblocking_state_lock(lock_path: Path):
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    if fcntl is not None:
        with lock_path.open("w", encoding="utf-8") as handle:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                yield False
                return
            try:
                yield True
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        return

    lock_dir = lock_path.with_suffix(lock_path.suffix + ".dir")
    try:  # pragma: no cover - exercised only without fcntl
        lock_dir.mkdir()
    except FileExistsError:
        yield False
        return
    try:
        yield True
    finally:
        shutil.rmtree(lock_dir, ignore_errors=True)


def is_git_repo(path: Path) -> bool:
    if not path.exists():
        return False
    result = run(["git", "-C", str(path), "rev-parse", "--is-inside-work-tree"], check=False)
    return result.returncode == 0 and result.stdout.strip() == "true"


def git_remote(repo: Path) -> str | None:
    result = git(repo, "remote", "get-url", "origin", check=False)
    if result.returncode != 0:
        return None
    remote = result.stdout.strip()
    return remote or None


def current_branch(repo: Path) -> str | None:
    result = git(repo, "branch", "--show-current", check=False)
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def local_branch_exists(repo: Path, branch: str) -> bool:
    if current_branch(repo) == branch:
        return True
    return git(repo, "rev-parse", "--verify", branch, check=False).returncode == 0


def remote_branch_exists(repo: Path, branch: str) -> bool:
    return git(repo, "ls-remote", "--exit-code", "--heads", "origin", branch, check=False).returncode == 0


def configure_git_identity(repo: Path) -> None:
    name = (
        os.environ.get("AR_RESOLVER_GIT_NAME")
        or os.environ.get("AR_GIT_NAME")
        or os.environ.get("AR_NOTES_GIT_NAME")
        or "Agentic Team"
    )
    email = (
        os.environ.get("AR_RESOLVER_GIT_EMAIL")
        or os.environ.get("AR_GIT_EMAIL")
        or os.environ.get("AR_NOTES_GIT_EMAIL")
        or "agentic-team@example.invalid"
    )
    git(repo, "config", "user.name", name)
    git(repo, "config", "user.email", email)


def commit_if_changed(repo: Path, message: str, paths: list[Path] | None = None) -> bool:
    configure_git_identity(repo)
    if paths is not None:
        if not paths:
            return False
        for path in paths:
            git(repo, "add", str(path.relative_to(repo)))
    else:
        git(repo, "add", ".")
    status = git(repo, "status", "--porcelain").stdout.strip()
    if not status:
        return False
    git(repo, "commit", "-m", message)
    return True


def push(repo: Path, branch: str | None = None) -> bool:
    remote = git_remote(repo)
    if not remote:
        return True
    branch = branch or current_branch(repo) or state_branch()
    result = git(repo, "push", "-u", "origin", branch, check=False)
    return result.returncode == 0


def pull_ff(repo: Path, branch: str | None = None, *, missing_ok: bool = False) -> None:
    remote = git_remote(repo)
    if not remote:
        return
    branch = branch or current_branch(repo)
    if branch:
        result = git(repo, "fetch", "origin", branch, check=False)
        if result.returncode != 0:
            detail = result.stderr.strip() or result.stdout.strip()
            if missing_ok and "couldn't find remote ref" in detail:
                return
            raise AgenticStateError(f"git fetch origin {branch} failed: {detail}")
        git(repo, "merge", "--ff-only", "FETCH_HEAD", check=False)
    else:
        git(repo, "fetch", "origin")


def ensure_local_git_repo(repo: Path, branch: str) -> Path:
    repo.mkdir(parents=True, exist_ok=True)
    if not (repo / ".git").exists():
        run(["git", "init", "-b", branch, str(repo)], check=False)
        if not (repo / ".git").exists():
            run(["git", "init", str(repo)])
            git(repo, "checkout", "-B", branch)
    configure_git_identity(repo)
    return repo


def create_orphan_branch(repo: Path, branch: str) -> None:
    git(repo, "checkout", "--orphan", branch)
    git(repo, "rm", "-rf", ".", check=False)
    for child in repo.iterdir():
        if child.name == ".git":
            continue
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()


def ensure_existing_state_repo(repo: Path, branch: str) -> Path:
    configure_git_identity(repo)
    if local_branch_exists(repo, branch):
        if current_branch(repo) != branch:
            git(repo, "checkout", branch)
    elif git_remote(repo) and remote_branch_exists(repo, branch):
        git(repo, "fetch", "origin", branch)
        git(repo, "checkout", "-B", branch, f"origin/{branch}")
    else:
        create_orphan_branch(repo, branch)
    return repo


def add_state_worktree(project_dir: Path, dest: Path, branch: str, *, use_remote: bool = True) -> Path:
    git(project_dir, "worktree", "prune", check=False)
    dest.parent.mkdir(parents=True, exist_ok=True)

    if local_branch_exists(project_dir, branch):
        git(project_dir, "worktree", "add", str(dest), branch)
    elif use_remote and git_remote(project_dir) and remote_branch_exists(project_dir, branch):
        git(project_dir, "fetch", "origin", branch)
        git(project_dir, "worktree", "add", "--track", "-b", branch, str(dest), f"origin/{branch}")
    else:
        git(project_dir, "worktree", "add", "--orphan", "-b", branch, str(dest))

    configure_git_identity(dest)
    return dest


def ensure_state_worktree_or_repo(
    project_dir: Path,
    dest: Path,
    branch: str,
    label: str,
    *,
    use_remote: bool = True,
) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)

    if is_git_repo(dest):
        return ensure_existing_state_repo(dest, branch)

    if dest.exists() and any(dest.iterdir()):
        raise AgenticStateError(f"{label} state path exists but is not a Git repo: {dest}")

    if is_git_repo(project_dir):
        return add_state_worktree(project_dir, dest, branch, use_remote=use_remote)

    # Launcher-managed projects are expected to be Git worktrees. Keep a small
    # fallback for direct command use without a project repo, but normal
    # project/work state now lives in linked worktrees.
    return ensure_local_git_repo(dest, branch)


def ensure_org_worktree(repo: Path) -> None:
    if git(repo, "rev-parse", "--verify", "HEAD", check=False).returncode == 0:
        return

    preferred = os.environ.get("AR_ORG_NOTES_BRANCH", "main")
    candidates = [preferred, "main", "master"]
    seen: set[str] = set()
    for branch in candidates:
        if not branch or branch in seen:
            continue
        seen.add(branch)
        if remote_branch_exists(repo, branch):
            git(repo, "fetch", "origin", branch)
            git(repo, "checkout", "-B", branch, f"origin/{branch}")
            return


def ensure_org_checkout(repo_url: str | None = None) -> Path | None:
    repo_url = repo_url or os.environ.get("AR_ORG_NOTES_REPO")
    if not repo_url:
        return None
    dest = org_checkout_path()
    dest.parent.mkdir(parents=True, exist_ok=True)
    if (dest / ".git").exists():
        configure_git_identity(dest)
        ensure_org_worktree(dest)
        return dest
    if dest.exists() and any(dest.iterdir()):
        raise AgenticStateError(f"Org notes checkout exists but is not a Git repo: {dest}")
    run(["git", "clone", repo_url, str(dest)])
    configure_git_identity(dest)
    ensure_org_worktree(dest)
    return dest


def ensure_project_checkout(project_dir: Path) -> Path:
    branch = state_branch()
    dest = project_state_path(project_dir)
    return ensure_state_worktree_or_repo(project_dir, dest, branch, "Project")


def ensure_work_state_checkout(
    project_dir: Path,
    branch_name: str,
    *,
    use_remote: bool = True,
) -> Path:
    active_work_branch = work_branch(branch_name)
    branch = work_state_branch(active_work_branch)
    dest = work_state_path(project_dir, active_work_branch)
    return ensure_state_worktree_or_repo(project_dir, dest, branch, "Work", use_remote=use_remote)


def ensure_work_state(
    project_dir: Path,
    branch_name: str,
    *,
    pull_remote: bool = True,
    use_remote: bool = True,
) -> Path:
    active_work_branch = work_branch(branch_name)
    repo = ensure_work_state_checkout(project_dir, active_work_branch, use_remote=use_remote)
    branch = work_state_branch(active_work_branch)
    if pull_remote and git_remote(repo):
        pull_ff(repo, branch, missing_ok=True)
    return repo


def run_parallel_refresh(tasks: list[tuple[str, Callable[[], None]]]) -> None:
    errors: list[tuple[str, Exception]] = []
    error_lock = threading.Lock()

    def worker(label: str, func: Callable[[], None]) -> None:
        try:
            func()
        except Exception as exc:  # pragma: no cover - exercised through caller failures
            with error_lock:
                errors.append((label, exc))

    threads = [threading.Thread(target=worker, args=(label, func)) for label, func in tasks]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    if errors:
        label, exc = errors[0]
        raise AgenticStateError(f"{label} refresh failed: {exc}") from exc


def active_heartbeat_count(heartbeat_dir: Path, stale_seconds: int) -> int:
    if not heartbeat_dir.exists():
        return 0
    now = time.time()
    active = 0
    for heartbeat in heartbeat_dir.glob("*.heartbeat"):
        try:
            age = now - heartbeat.stat().st_mtime
        except FileNotFoundError:
            continue
        if age <= stale_seconds:
            active += 1
        else:
            heartbeat.unlink(missing_ok=True)
    return active


def wait_for_refresh_interval(heartbeat_dir: Path, interval_seconds: int, stale_seconds: int) -> bool:
    deadline = time.time() + interval_seconds
    while time.time() < deadline:
        if active_heartbeat_count(heartbeat_dir, stale_seconds) == 0:
            return False
        time.sleep(min(2.0, max(0.1, deadline - time.time())))
    return active_heartbeat_count(heartbeat_dir, stale_seconds) > 0
