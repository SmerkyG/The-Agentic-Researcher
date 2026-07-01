"""Shared Git-backed Agentic Team state mechanics.

This module owns project/work-branch identity, local state checkout management,
locking, and ordinary Git synchronization. Capabilities use it as substrate;
they own the files and schemas they place in those checkouts.
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


def work_branch_path_fragment(value: str) -> Path:
    return Path(*work_branch(value).split("/"))


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


def project_remote_url(project_dir: Path) -> str | None:
    result = run(
        ["git", "-C", str(project_dir), "remote", "get-url", "origin"],
        check=False,
    )
    if result.returncode != 0:
        return None
    remote = result.stdout.strip()
    return remote or None


def project_remote_name(remote: str) -> str:
    value = remote.strip()
    value = re.sub(r"#.*$", "", value)
    value = value.rstrip("/")

    match = re.match(r"^[A-Za-z][A-Za-z0-9+.-]*://(?:[^/]+)/(.*)$", value)
    if match:
        value = match.group(1)
    elif value.startswith("file://"):
        value = value[7:]
    else:
        scp = re.match(r"^(?:[^@/:]+@)?[^/:]+:(.+)$", value)
        if scp:
            value = scp.group(1)

    value = value.rstrip("/").removesuffix(".git")
    return Path(value).name or "project"


def is_remote_repo_spec(value: str) -> bool:
    value = value.strip()
    if re.match(r"^[A-Za-z][A-Za-z0-9+.-]*://", value):
        return True
    if re.match(r"^[A-Za-z]:[\\/]", value):
        return False
    return re.match(r"^(?:[^@/:]+@)?[^/:]+:.+$", value) is not None


def project_id(project_dir: Path, explicit: str | None = None) -> str:
    if explicit:
        return slugify(explicit, default="project")
    if os.environ.get("AR_PROJECT_ID"):
        return slugify(os.environ["AR_PROJECT_ID"], default="project")
    remote = project_remote_url(project_dir)
    if remote:
        return slugify(project_remote_name(remote), default="project")
    raise AgenticStateError(
        "Project id could not be inferred because this project has no git remote. "
        "Pass --project-id to agentic-team or set AR_PROJECT_ID."
    )


def org_checkout_path() -> Path:
    return state_root() / "repos" / "org-agentic-notes"


def project_state_path(project_dir: Path, explicit_project_id: str | None = None) -> Path:
    return state_root() / "projects" / project_id(project_dir, explicit_project_id) / "agentic-state"


def work_state_path(
    project_dir: Path,
    branch: str,
    explicit_project_id: str | None = None,
) -> Path:
    return (
        state_root()
        / "projects"
        / project_id(project_dir, explicit_project_id)
        / "work-state"
        / work_branch_path_fragment(branch)
    )


def lock_file_for(name: str) -> Path:
    return state_root() / "locks" / f"{slugify(name, default='state')}.lock"


def org_lock_path() -> Path:
    return lock_file_for("org-agentic-notes")


def project_lock_path(project_dir: Path, explicit_project_id: str | None = None) -> Path:
    return lock_file_for(f"project-{project_id(project_dir, explicit_project_id)}")


def work_lock_path(
    project_dir: Path,
    work_branch_value: str | None,
    explicit_project_id: str | None = None,
) -> Path:
    pid = project_id(project_dir, explicit_project_id)
    return lock_file_for(f"project-{pid}-work-{work_branch_id(work_branch_value)}")


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
    if paths:
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


def project_origin(project_dir: Path) -> str | None:
    if not is_git_repo(project_dir):
        return None
    remote = git_remote(project_dir)
    if remote:
        return remote
    top = run(["git", "-C", str(project_dir), "rev-parse", "--show-toplevel"]).stdout.strip()
    return top or None


def ensure_project_checkout(project_dir: Path, explicit_project_id: str | None = None) -> Path:
    branch = state_branch()
    dest = project_state_path(project_dir, explicit_project_id)
    origin = project_origin(project_dir)
    dest.parent.mkdir(parents=True, exist_ok=True)

    if (dest / ".git").exists():
        configure_git_identity(dest)
        if local_branch_exists(dest, branch):
            if current_branch(dest) != branch:
                git(dest, "checkout", branch)
        elif git_remote(dest) and remote_branch_exists(dest, branch):
            git(dest, "fetch", "origin", branch)
            git(dest, "checkout", "-B", branch, f"origin/{branch}")
        else:
            create_orphan_branch(dest, branch)
        return dest

    if dest.exists() and any(dest.iterdir()):
        raise AgenticStateError(f"Project state checkout exists but is not a Git repo: {dest}")

    if origin:
        run(["git", "clone", origin, str(dest)])
        configure_git_identity(dest)
        if remote_branch_exists(dest, branch):
            git(dest, "fetch", "origin", branch)
            git(dest, "checkout", "-B", branch, f"origin/{branch}")
        else:
            create_orphan_branch(dest, branch)
    else:
        ensure_local_git_repo(dest, branch)
    return dest


def ensure_work_state_checkout(
    project_dir: Path,
    branch_name: str,
    explicit_project_id: str | None = None,
) -> Path:
    active_work_branch = work_branch(branch_name)
    branch = work_state_branch(active_work_branch)
    dest = work_state_path(project_dir, active_work_branch, explicit_project_id)
    origin = project_origin(project_dir)
    dest.parent.mkdir(parents=True, exist_ok=True)

    if (dest / ".git").exists():
        configure_git_identity(dest)
        if local_branch_exists(dest, branch):
            if current_branch(dest) != branch:
                git(dest, "checkout", branch)
        elif git_remote(dest) and remote_branch_exists(dest, branch):
            git(dest, "fetch", "origin", branch)
            git(dest, "checkout", "-B", branch, f"origin/{branch}")
        else:
            create_orphan_branch(dest, branch)
        return dest

    if dest.exists() and any(dest.iterdir()):
        raise AgenticStateError(f"Work state checkout exists but is not a Git repo: {dest}")

    if origin:
        run(["git", "clone", origin, str(dest)])
        configure_git_identity(dest)
        if remote_branch_exists(dest, branch):
            git(dest, "fetch", "origin", branch)
            git(dest, "checkout", "-B", branch, f"origin/{branch}")
        else:
            create_orphan_branch(dest, branch)
    else:
        ensure_local_git_repo(dest, branch)
    return dest


def ensure_work_state(
    project_dir: Path,
    branch_name: str,
    explicit_project_id: str | None = None,
    *,
    pull_remote: bool = True,
) -> Path:
    active_work_branch = work_branch(branch_name)
    repo = ensure_work_state_checkout(project_dir, active_work_branch, explicit_project_id)
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
