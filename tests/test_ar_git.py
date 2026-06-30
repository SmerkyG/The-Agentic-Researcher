import json
import os
import subprocess
from pathlib import Path

import yaml


REPO_ROOT = Path(__file__).resolve().parents[1]
AR_TOOL = REPO_ROOT / "scripts" / "ar-tool"


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


def run_tool(tool: str, data: dict, *, env: dict[str, str], check: bool = True) -> subprocess.CompletedProcess[str]:
    return run([str(AR_TOOL), "run", tool], env=env, input=yaml.safe_dump(data, sort_keys=False), check=check)


def init_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "project"
    repo.mkdir()
    run(["git", "init"], cwd=repo)
    git(repo, "config", "user.name", "Test User")
    git(repo, "config", "user.email", "test@example.com")
    (repo / "README.md").write_text("initial\n", encoding="utf-8")
    git(repo, "add", "README.md")
    git(repo, "commit", "-m", "initial")
    git(repo, "switch", "-c", "agent/kernel-search")
    return repo


def test_commit_snapshot_uses_temp_index_and_advances_topic_branch(tmp_path: Path) -> None:
    repo = init_repo(tmp_path)
    env = os.environ.copy()
    env["AR_STATE_ROOT"] = str(tmp_path / "state")
    env["AR_AGENT_TOPIC"] = "kernel-search"
    notes_call = tmp_path / "notes-call.json"
    fake_notes = tmp_path / "fake-ar-notes"
    fake_notes.write_text(
        "#!/usr/bin/env python3\n"
        "import json, os, pathlib, sys\n"
        "pathlib.Path(os.environ['FAKE_NOTES_CALL']).write_text(json.dumps(sys.argv[1:]), encoding='utf-8')\n"
        "print('kernel-search/E0001_snapshot-experiment')\n",
        encoding="utf-8",
    )
    fake_notes.chmod(0o755)
    env["AR_NOTES_CLI"] = str(fake_notes)
    env["FAKE_NOTES_CALL"] = str(notes_call)

    (repo / "staged.txt").write_text("keep staged\n", encoding="utf-8")
    git(repo, "add", "staged.txt")
    (repo / "README.md").write_text("snapshotted\n", encoding="utf-8")
    (repo / "TODO.md").write_text("- [ ] follow up\n", encoding="utf-8")

    request = {
        "project_dir": str(repo),
        "topic": "kernel-search",
        "paths": ["README.md", "TODO.md"],
        "commit_message": "test: commit snapshot",
        "checks": ["test -f TODO.md"],
        "after_commit": {
            "experiment_log": {
                "title": "Snapshot experiment",
                "short_description": "snapshot experiment",
                "status": "completed",
                "key_result": "helper produced commit",
            },
        },
    }

    snapshot = json.loads(run_tool("branch-snapshot", request, env=env).stdout)

    assert snapshot["name_status"] == ["M\tREADME.md", "A\tTODO.md"]
    assert Path(snapshot["name_status_path"]).exists()
    assert git(repo, "diff", "--cached", "--name-only") == "staged.txt"

    (repo / "README.md").write_text("continued work after snapshot\n", encoding="utf-8")

    committed = json.loads(
        run_tool(
            "branch-commit",
            {"snapshot_dir": snapshot["snapshot_dir"], "background": False},
            env=env,
        ).stdout
    )

    assert committed["state"] == "committed"
    assert committed["experiment_log_state"] == "logged"
    assert committed["experiment_log_id"] == "kernel-search/E0001_snapshot-experiment"
    assert git(repo, "log", "-1", "--format=%s") == "test: commit snapshot"
    assert git(repo, "show", "HEAD:README.md") == "snapshotted"
    assert git(repo, "show", "HEAD:TODO.md") == "- [ ] follow up"
    assert (repo / "README.md").read_text(encoding="utf-8") == "continued work after snapshot\n"
    assert git(repo, "diff", "--cached", "--name-only") == "staged.txt"
    assert "README.md" in git(repo, "status", "--short", "--", "README.md")
    assert git(repo, "status", "--short", "--", "TODO.md") == ""

    experiment_request = yaml.safe_load(
        Path(committed["experiment_request_path"]).read_text(encoding="utf-8")
    )
    assert experiment_request["code"]["branch"] == "agent/kernel-search"
    assert experiment_request["code"]["commit"] == committed["commit"]
    assert experiment_request["topic"] == "kernel-search"
    notes_args = json.loads(notes_call.read_text(encoding="utf-8"))
    assert notes_args[:2] == ["log-experiment", "--request"]
    assert notes_args[2] != committed["experiment_request_path"]
    assert "--project-dir" in notes_args
    assert str(repo) in notes_args
    assert "--topic" in notes_args
    assert "kernel-search" in notes_args

    status = json.loads(
        run_tool("branch-commit-status", {"snapshot_dir": snapshot["snapshot_dir"]}, env=env).stdout
    )
    assert status["state"] == "committed"
    assert status["commit"] == committed["commit"]
    assert status["experiment_log_state"] == "logged"
    assert status["experiment_log_id"] == "kernel-search/E0001_snapshot-experiment"


def test_commit_snapshot_reports_experiment_log_failure_after_commit(tmp_path: Path) -> None:
    repo = init_repo(tmp_path)
    env = os.environ.copy()
    env["AR_STATE_ROOT"] = str(tmp_path / "state")
    env["AR_AGENT_TOPIC"] = "kernel-search"
    fake_notes = tmp_path / "fake-ar-notes-fail"
    fake_notes.write_text(
        "#!/bin/sh\n"
        "echo 'simulated experiment log failure'\n"
        "exit 17\n",
        encoding="utf-8",
    )
    fake_notes.chmod(0o755)
    env["AR_NOTES_CLI"] = str(fake_notes)

    (repo / "README.md").write_text("snapshotted\n", encoding="utf-8")
    request = {
        "project_dir": str(repo),
        "topic": "kernel-search",
        "paths": ["README.md"],
        "commit_message": "test: commit despite log failure",
        "after_commit": {
            "experiment_log": {
                "title": "Snapshot experiment",
                "short_description": "snapshot experiment",
                "status": "completed",
                "key_result": "helper produced commit",
            },
        },
    }

    snapshot = json.loads(run_tool("branch-snapshot", request, env=env).stdout)
    committed = json.loads(
        run_tool(
            "branch-commit",
            {"snapshot_dir": snapshot["snapshot_dir"], "background": False},
            env=env,
        ).stdout
    )

    assert committed["state"] == "committed"
    assert committed["experiment_log_state"] == "failed"
    assert "simulated experiment log failure" in committed["experiment_log_error"]
    assert git(repo, "log", "-1", "--format=%s") == "test: commit despite log failure"
    status = json.loads(
        run_tool("branch-commit-status", {"snapshot_dir": snapshot["snapshot_dir"]}, env=env).stdout
    )
    assert status["state"] == "committed"
    assert status["experiment_log_state"] == "failed"
    assert "simulated experiment log failure" in status["experiment_log_error"]


def test_snapshot_rejects_broad_paths(tmp_path: Path) -> None:
    repo = init_repo(tmp_path)
    env = os.environ.copy()
    env["AR_STATE_ROOT"] = str(tmp_path / "state")
    env["AR_AGENT_TOPIC"] = "kernel-search"
    (repo / "README.md").write_text("changed\n", encoding="utf-8")

    for broad_path in [".", "./", "*", "src/*.py"]:
        result = run_tool(
            "branch-snapshot",
            {
                "project_dir": str(repo),
                "topic": "kernel-search",
                "paths": [broad_path],
                "commit_message": "test: rejected broad path",
            },
            env=env,
            check=False,
        )
        assert result.returncode == 1
        assert "branch snapshot request" in result.stderr
