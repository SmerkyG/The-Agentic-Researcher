import json
import os
import subprocess
import time
from pathlib import Path

import yaml


REPO_ROOT = Path(__file__).resolve().parents[1]
BIN_DIR = REPO_ROOT / "capabilities" / "branch" / "bin"


def run(
    command: list[str],
    *,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
    check: bool = True,
    input: str | None = None,
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(command, cwd=cwd, env=env, input=input, text=True, capture_output=True)
    if check and result.returncode != 0:
        raise AssertionError(
            f"{' '.join(command)} failed\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
        )
    return result


def git(repo: Path, *args: str) -> str:
    return run(["git", *args], cwd=repo).stdout.strip()


def write_yaml(path: Path, data: dict) -> None:
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


def run_agent_command(command_name: str, data: dict, *, env: dict[str, str], check: bool = True) -> subprocess.CompletedProcess[str]:
    return run([str(BIN_DIR / command_name)], env=env, input=yaml.safe_dump(data, sort_keys=False), check=check)


def init_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "project"
    repo.mkdir()
    run(["git", "init"], cwd=repo)
    git(repo, "config", "user.name", "Test User")
    git(repo, "config", "user.email", "test@example.com")
    (repo / "README.md").write_text("initial\n", encoding="utf-8")
    git(repo, "add", "README.md")
    git(repo, "commit", "-m", "initial")
    git(repo, "switch", "-c", "kernel-search")
    return repo


def init_repo_without_persistent_identity(tmp_path: Path) -> Path:
    repo = tmp_path / "project"
    repo.mkdir()
    run(["git", "init"], cwd=repo)
    (repo / "README.md").write_text("initial\n", encoding="utf-8")
    git(repo, "add", "README.md")
    run(
        [
            "git",
            "-c",
            "user.name=Test User",
            "-c",
            "user.email=test@example.com",
            "commit",
            "-m",
            "initial",
        ],
        cwd=repo,
    )
    git(repo, "switch", "-c", "kernel-search")
    return repo


def test_commit_snapshot_uses_temp_index_and_advances_work_branch(tmp_path: Path) -> None:
    repo = init_repo(tmp_path)
    env = os.environ.copy()
    env["AR_STATE_ROOT"] = str(tmp_path / "state")
    env["AR_WORK_BRANCH"] = "kernel-search"
    env["PATH"] = f"{BIN_DIR}:{env['PATH']}"

    (repo / "staged.txt").write_text("keep staged\n", encoding="utf-8")
    git(repo, "add", "staged.txt")
    (repo / "README.md").write_text("snapshotted\n", encoding="utf-8")
    src = repo / "src"
    src.mkdir()
    (src / "kernel.py").write_text("print('snap')\n", encoding="utf-8")

    request = {
        "project_dir": str(repo),
        "work_branch": "kernel-search",
        "paths": ["README.md", "src/kernel.py"],
        "commit_message": "test: commit snapshot",
        "checks": ["test -f src/kernel.py"],
    }

    snapshot = json.loads(run_agent_command("branch-snapshot", request, env=env).stdout)

    expected_runtime = tmp_path / "project-at" / ".runtime"
    assert Path(snapshot["snapshot_dir"]).is_relative_to(expected_runtime / "commit-snapshots")
    assert snapshot["name_status"] == ["M\tREADME.md", "A\tsrc/kernel.py"]
    assert Path(snapshot["name_status_path"]).exists()
    assert not (Path(env["AR_STATE_ROOT"]) / "commit-snapshots").exists()
    assert git(repo, "diff", "--cached", "--name-only") == "staged.txt"

    (repo / "README.md").write_text("continued work after snapshot\n", encoding="utf-8")

    committed = json.loads(
        run_agent_command(
            "branch-commit",
            {"snapshot_dir": snapshot["snapshot_dir"], "background": False},
            env=env,
        ).stdout
    )

    assert committed["state"] == "committed"
    assert "experiment_log_state" not in committed
    assert "experiment_log_id" not in committed
    assert git(repo, "log", "-1", "--format=%s") == "test: commit snapshot"
    assert git(repo, "show", "HEAD:README.md") == "snapshotted"
    assert git(repo, "show", "HEAD:src/kernel.py") == "print('snap')"
    assert (repo / "README.md").read_text(encoding="utf-8") == "continued work after snapshot\n"
    assert git(repo, "diff", "--cached", "--name-only") == "staged.txt"
    assert "README.md" in git(repo, "status", "--short", "--", "README.md")
    assert git(repo, "status", "--short", "--", "src/kernel.py") == ""

    status = json.loads(
        run_agent_command("branch-commit-status", {"snapshot_dir": snapshot["snapshot_dir"]}, env=env).stdout
    )
    assert status["state"] == "committed"
    assert status["commit"] == committed["commit"]
    assert "experiment_log_state" not in status
    metadata = yaml.safe_load((Path(snapshot["snapshot_dir"]) / "metadata.yaml").read_text(encoding="utf-8"))
    assert "after_commit" not in metadata


def test_commit_snapshot_does_not_leak_tool_virtualenv_into_checks(tmp_path: Path) -> None:
    repo = init_repo(tmp_path)
    env = os.environ.copy()
    env["AR_STATE_ROOT"] = str(tmp_path / "state")
    env["AR_WORK_BRANCH"] = "kernel-search"
    env["PATH"] = f"{BIN_DIR}:{env['PATH']}"
    env["VIRTUAL_ENV"] = str(tmp_path / "unrelated-tool-environment")
    (repo / "README.md").write_text("check environment\n", encoding="utf-8")

    snapshot = json.loads(
        run_agent_command(
            "branch-snapshot",
            {
                "project_dir": str(repo),
                "work_branch": "kernel-search",
                "paths": ["README.md"],
                "commit_message": "test: isolate check environment",
                "checks": ['test -z "$VIRTUAL_ENV"'],
            },
            env=env,
        ).stdout
    )

    committed = json.loads(
        run_agent_command(
            "branch-commit",
            {"snapshot_dir": snapshot["snapshot_dir"], "background": False},
            env=env,
        ).stdout
    )

    assert committed["state"] == "committed"
    assert committed["checks"][0]["returncode"] == 0


def test_background_commit_reports_running_check_and_streams_log(tmp_path: Path) -> None:
    repo = init_repo(tmp_path)
    env = os.environ.copy()
    env["AR_STATE_ROOT"] = str(tmp_path / "state")
    env["AR_WORK_BRANCH"] = "kernel-search"
    env["PATH"] = f"{BIN_DIR}:{env['PATH']}"
    (repo / "README.md").write_text("background commit\n", encoding="utf-8")

    snapshot = json.loads(
        run_agent_command(
            "branch-snapshot",
            {
                "project_dir": str(repo),
                "work_branch": "kernel-search",
                "paths": ["README.md"],
                "commit_message": "test: background commit",
                "checks": ["printf 'begin check\\n'; sleep 1; printf 'end check\\n'"],
            },
            env=env,
        ).stdout
    )

    started = json.loads(
        run_agent_command(
            "branch-commit",
            {"snapshot_dir": snapshot["snapshot_dir"], "background": True},
            env=env,
        ).stdout
    )
    assert started["state"] == "queued"

    running_status: dict | None = None
    deadline = time.time() + 5
    while time.time() < deadline:
        status = json.loads(
            run_agent_command("branch-commit-status", {"snapshot_dir": snapshot["snapshot_dir"]}, env=env).stdout
        )
        if status.get("current_check"):
            running_status = status
            break
        time.sleep(0.05)

    assert running_status is not None
    assert running_status["state"] == "running"
    assert running_status["pid_alive"] is True
    assert running_status["current_check_index"] == 1
    assert "begin check" in Path(running_status["check_log"]).read_text(encoding="utf-8")

    deadline = time.time() + 10
    while time.time() < deadline:
        status = json.loads(
            run_agent_command("branch-commit-status", {"snapshot_dir": snapshot["snapshot_dir"]}, env=env).stdout
        )
        if status.get("state") == "committed":
            break
        time.sleep(0.1)
    else:
        raise AssertionError(f"background commit did not finish: {status}")

    assert status["commit"]
    assert status["checks"][0]["returncode"] == 0
    check_log = Path(status["check_log"]).read_text(encoding="utf-8")
    assert "begin check" in check_log
    assert "end check" in check_log
    assert git(repo, "log", "-1", "--format=%s") == "test: background commit"


def test_branch_commit_status_accepts_snapshot_dir_or_status_path(tmp_path: Path) -> None:
    repo = init_repo(tmp_path)
    env = os.environ.copy()
    env["AR_STATE_ROOT"] = str(tmp_path / "state")
    env["AR_WORK_BRANCH"] = "kernel-search"
    (repo / "README.md").write_text("changed\n", encoding="utf-8")
    snapshot = json.loads(
        run_agent_command(
            "branch-snapshot",
            {
                "project_dir": str(repo),
                "paths": ["README.md"],
                "commit_message": "test: status path",
            },
            env=env,
        ).stdout
    )

    by_snapshot_dir = json.loads(
        run([str(BIN_DIR / "branch-commit-status"), snapshot["snapshot_dir"]], env=env).stdout
    )
    status_path = str(Path(snapshot["snapshot_dir"]) / "status.yaml")
    by_status_path = json.loads(
        run([str(BIN_DIR / "branch-commit-status"), status_path], env=env).stdout
    )

    assert by_snapshot_dir["snapshot_dir"] == snapshot["snapshot_dir"]
    assert by_status_path["snapshot_dir"] == snapshot["snapshot_dir"]


def test_branch_commit_cleanup_removes_committed_snapshot_and_worktree(tmp_path: Path) -> None:
    repo = init_repo(tmp_path)
    env = os.environ.copy()
    env["AR_STATE_ROOT"] = str(tmp_path / "state")
    env["AR_WORK_BRANCH"] = "kernel-search"
    (repo / "README.md").write_text("cleanup target\n", encoding="utf-8")
    snapshot = json.loads(
        run_agent_command(
            "branch-snapshot",
            {
                "project_dir": str(repo),
                "paths": ["README.md"],
                "commit_message": "test: cleanup target",
            },
            env=env,
        ).stdout
    )
    committed = json.loads(
        run_agent_command(
            "branch-commit",
            {"snapshot_dir": snapshot["snapshot_dir"], "background": False},
            env=env,
        ).stdout
    )
    snapshot_dir = Path(snapshot["snapshot_dir"])
    worktree = Path(committed["worktree"])
    assert snapshot_dir.is_relative_to(tmp_path / "project-at" / ".runtime" / "commit-snapshots")
    assert worktree.is_relative_to(tmp_path / "project-at" / ".runtime" / "commit-worktrees")
    assert snapshot_dir.exists()
    assert worktree.exists()
    assert str(worktree) in git(repo, "worktree", "list", "--porcelain")

    dry_run = json.loads(
        run_agent_command(
            "branch-commit-cleanup",
            {
                "dry_run": True,
                "older_than_days": 0,
                "states": ["committed"],
                "project_dir": str(repo),
            },
            env=env,
        ).stdout
    )
    assert dry_run["planned_count"] == 1
    assert dry_run["removed_count"] == 0
    assert snapshot_dir.exists()
    assert worktree.exists()

    cleaned = json.loads(
        run_agent_command(
            "branch-commit-cleanup",
            {
                "dry_run": False,
                "older_than_days": 0,
                "states": ["committed"],
                "project_dir": str(repo),
            },
            env=env,
        ).stdout
    )
    assert cleaned["removed_count"] == 1
    assert cleaned["planned_count"] == 0
    assert not snapshot_dir.exists()
    assert not worktree.exists()
    assert str(worktree) not in git(repo, "worktree", "list", "--porcelain")


def test_branch_commit_cleanup_skips_live_running_snapshot(tmp_path: Path) -> None:
    env = os.environ.copy()
    env["AR_STATE_ROOT"] = str(tmp_path / "state")
    env["AR_RUNTIME_ROOT"] = str(tmp_path / "project-at" / ".runtime")
    snapshot_dir = Path(env["AR_RUNTIME_ROOT"]) / "commit-snapshots" / "running"
    worktree = Path(env["AR_RUNTIME_ROOT"]) / "commit-worktrees" / "running" / "kernel-search"
    snapshot_dir.mkdir(parents=True)
    worktree.mkdir(parents=True)
    timestamp = "2000-01-01T00:00:00+00:00"
    write_yaml(
        snapshot_dir / "metadata.yaml",
        {
            "snapshot_id": "running",
            "created_at": timestamp,
            "project_dir": str(tmp_path / "project"),
            "runtime_root": env["AR_RUNTIME_ROOT"],
        },
    )
    write_yaml(
        snapshot_dir / "status.yaml",
        {
            "snapshot_id": "running",
            "state": "running",
            "created_at": timestamp,
            "updated_at": timestamp,
            "pid": os.getpid(),
            "worktree": str(worktree),
        },
    )

    result = json.loads(
        run_agent_command(
            "branch-commit-cleanup",
            {
                "dry_run": False,
                "older_than_days": 0,
                "states": ["running"],
                "include_active": True,
            },
            env=env,
        ).stdout
    )

    assert result["removed_count"] == 0
    assert result["skipped_count"] == 1
    assert result["skipped"][0]["reason"] == "pid alive"
    assert snapshot_dir.exists()
    assert worktree.exists()


def test_commit_snapshot_times_out_stuck_check(tmp_path: Path) -> None:
    repo = init_repo(tmp_path)
    env = os.environ.copy()
    env["AR_STATE_ROOT"] = str(tmp_path / "state")
    env["AR_WORK_BRANCH"] = "kernel-search"
    env["PATH"] = f"{BIN_DIR}:{env['PATH']}"
    (repo / "README.md").write_text("timeout check\n", encoding="utf-8")

    snapshot = json.loads(
        run_agent_command(
            "branch-snapshot",
            {
                "project_dir": str(repo),
                "work_branch": "kernel-search",
                "paths": ["README.md"],
                "commit_message": "test: timeout check",
                "checks": ["sleep 5"],
                "check_timeout_seconds": 1,
            },
            env=env,
        ).stdout
    )

    result = run_agent_command(
        "branch-commit",
        {"snapshot_dir": snapshot["snapshot_dir"], "background": False},
        env=env,
        check=False,
    )

    assert result.returncode == 1
    assert "check timed out after 1 seconds" in result.stderr
    status = json.loads(
        run_agent_command("branch-commit-status", {"snapshot_dir": snapshot["snapshot_dir"]}, env=env).stdout
    )
    assert status["state"] == "failed"
    assert "check timed out after 1 seconds" in status["error"]
    assert "[timeout after 1 seconds]" in Path(status["check_log"]).read_text(encoding="utf-8")
    assert git(repo, "log", "-1", "--format=%s") == "initial"


def test_commit_snapshot_checks_git_identity_before_running_checks(tmp_path: Path) -> None:
    repo = init_repo_without_persistent_identity(tmp_path)
    isolated_home = tmp_path / "home"
    isolated_home.mkdir()
    check_ran = tmp_path / "check-ran"
    env = os.environ.copy()
    env["AR_STATE_ROOT"] = str(tmp_path / "state")
    env["AR_WORK_BRANCH"] = "kernel-search"
    env["HOME"] = str(isolated_home)
    env["PATH"] = f"{BIN_DIR}:{env['PATH']}"
    (repo / "README.md").write_text("identity check\n", encoding="utf-8")

    snapshot = json.loads(
        run_agent_command(
            "branch-snapshot",
            {
                "project_dir": str(repo),
                "work_branch": "kernel-search",
                "paths": ["README.md"],
                "commit_message": "test: missing identity",
                "checks": [f"touch {check_ran}"],
            },
            env=env,
        ).stdout
    )

    result = run_agent_command(
        "branch-commit",
        {"snapshot_dir": snapshot["snapshot_dir"], "background": False},
        env=env,
        check=False,
    )

    assert result.returncode == 1
    assert "Git commit identity is not configured" in result.stderr
    assert not check_ran.exists()
    status = json.loads(
        run_agent_command("branch-commit-status", {"snapshot_dir": snapshot["snapshot_dir"]}, env=env).stdout
    )
    assert status["state"] == "failed"
    assert "Git commit identity is not configured" in status["error"]
    assert git(repo, "log", "-1", "--format=%s") == "initial"


def test_commit_snapshot_uses_configured_agentic_team_identity(tmp_path: Path) -> None:
    repo = init_repo_without_persistent_identity(tmp_path)
    isolated_home = tmp_path / "home"
    isolated_home.mkdir()
    env = os.environ.copy()
    env["AR_STATE_ROOT"] = str(tmp_path / "state")
    env["AR_WORK_BRANCH"] = "kernel-search"
    env["AR_GIT_NAME"] = "Agentic Test"
    env["AR_GIT_EMAIL"] = "agentic-test@example.com"
    env["HOME"] = str(isolated_home)
    env["PATH"] = f"{BIN_DIR}:{env['PATH']}"
    (repo / "README.md").write_text("identity from setup\n", encoding="utf-8")

    snapshot = json.loads(
        run_agent_command(
            "branch-snapshot",
            {
                "project_dir": str(repo),
                "work_branch": "kernel-search",
                "paths": ["README.md"],
                "commit_message": "test: configured identity",
            },
            env=env,
        ).stdout
    )

    committed = json.loads(
        run_agent_command(
            "branch-commit",
            {"snapshot_dir": snapshot["snapshot_dir"], "background": False},
            env=env,
        ).stdout
    )

    assert committed["state"] == "committed"
    assert git(repo, "log", "-1", "--format=%s") == "test: configured identity"
    assert git(repo, "log", "-1", "--format=%an <%ae>") == "Agentic Test <agentic-test@example.com>"
    assert git(repo, "config", "--get", "user.name") == "Agentic Test"
    assert git(repo, "config", "--get", "user.email") == "agentic-test@example.com"


def test_branch_commands_have_help() -> None:
    for command_name in ["branch-snapshot", "branch-commit", "branch-commit-status", "branch-commit-cleanup"]:
        result = run([str(BIN_DIR / command_name), "--help"])
        assert result.returncode == 0
        assert "Reads YAML from stdin" in result.stdout
        assert "snapshot_dir" in result.stdout or "paths" in result.stdout


def test_snapshot_rejects_broad_paths(tmp_path: Path) -> None:
    repo = init_repo(tmp_path)
    env = os.environ.copy()
    env["AR_STATE_ROOT"] = str(tmp_path / "state")
    env["AR_WORK_BRANCH"] = "kernel-search"
    (repo / "README.md").write_text("changed\n", encoding="utf-8")

    for broad_path in [".", "./", "*", "src/*.py"]:
        result = run_agent_command(
            "branch-snapshot",
            {
                "project_dir": str(repo),
                "work_branch": "kernel-search",
                "paths": [broad_path],
                "commit_message": "test: rejected broad path",
            },
            env=env,
            check=False,
        )
        assert result.returncode == 1
        assert "branch snapshot request" in result.stderr
