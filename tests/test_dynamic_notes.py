import json
import os
import shutil
import stat
import subprocess
import sys
import time
import importlib.util
from importlib.machinery import SourceFileLoader
from pathlib import Path
from types import SimpleNamespace

import yaml


REPO_ROOT = Path(__file__).resolve().parents[1]
AR_NOTES = REPO_ROOT / "scripts" / "ar-notes"
AGENTIC_RESEARCHER = REPO_ROOT / "agentic-researcher"


def run(
    command: list[str],
    *,
    env: dict[str, str] | None = None,
    cwd: Path | None = None,
    check: bool = True,
    input: str | None = None,
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        command,
        cwd=cwd or REPO_ROOT,
        env=env,
        input=input,
        text=True,
        capture_output=True,
    )
    if check and result.returncode != 0:
        raise AssertionError(
            f"{' '.join(command)} failed\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
        )
    return result


def git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return run(["git", *args], cwd=repo, check=check)


def configure_git(repo: Path) -> None:
    git(repo, "config", "user.name", "Test User")
    git(repo, "config", "user.email", "test@example.com")


def init_bare_remote(tmp_path: Path, name: str, files: dict[str, str]) -> Path:
    bare = tmp_path / f"{name}.git"
    work = tmp_path / f"{name}-seed"
    run(["git", "init", "--bare", str(bare)])
    run(["git", "clone", str(bare), str(work)])
    configure_git(work)
    git(work, "checkout", "-b", "main")
    for rel, content in files.items():
        path = work / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    git(work, "add", *files.keys())
    git(work, "commit", "-m", "seed")
    git(work, "push", "-u", "origin", "main")
    run(["git", "--git-dir", str(bare), "symbolic-ref", "HEAD", "refs/heads/main"])
    return bare


def clone_project(tmp_path: Path, remote: Path, name: str = "project") -> Path:
    project = tmp_path / name
    run(["git", "clone", str(remote), str(project)])
    configure_git(project)
    return project


def base_env(tmp_path: Path, org_remote: Path | None = None) -> dict[str, str]:
    env = os.environ.copy()
    env.update(
        {
            "AR_STATE_ROOT": str(tmp_path / "state"),
            "AR_MAIN_AGENT": "research-coordinator",
            "AR_USER_ID": "alice",
            "AR_PROJECT_ID": "sparse-transformer-2026",
            "AR_AGENTIC_STATE_BRANCH": "agentic/state",
            "AR_NOTES_GIT_NAME": "Agentic Test",
            "AR_NOTES_GIT_EMAIL": "agentic-test@example.com",
        }
    )
    if org_remote is not None:
        env["AR_ORG_NOTES_REPO"] = str(org_remote)
    return env


def write_yaml(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


def make_request(tmp_path: Path, data: dict) -> Path:
    path = tmp_path / f"request-{len(list(tmp_path.glob('request-*.yaml')))}.yaml"
    write_yaml(path, data)
    return path


def state_checkout(env: dict[str, str], project_id: str = "sparse-transformer-2026") -> Path:
    return Path(env["AR_STATE_ROOT"]) / "projects" / project_id / "agentic-state"


def org_checkout(env: dict[str, str]) -> Path:
    return Path(env["AR_STATE_ROOT"]) / "repos" / "org-agentic-notes"


def seed_org_remote(tmp_path: Path) -> Path:
    return init_bare_remote(
        tmp_path,
        "org-notes",
        {
            "notes/always-injected.md": "# Org Notes\n\nOrg body.\n",
            "notes/triton.md": "# Triton\n\n",
            "notes/pytorch.md": "# PyTorch\n\n",
            "roles/gpu-kernel-engineer/notes/always-injected.md": "# Role Notes\n\nRole body.\n",
            "roles/gpu-kernel-engineer/notes/kernel-optimization.md": "# Kernel Optimization\n\n",
        },
    )


def seed_project_remote(tmp_path: Path) -> Path:
    return init_bare_remote(tmp_path, "project", {"README.md": "# Project\n"})


def test_generate_instruction_injects_always_injected_notes_and_lists_on_demand_notes(tmp_path: Path) -> None:
    org_remote = seed_org_remote(tmp_path)
    project_remote = seed_project_remote(tmp_path)
    project = clone_project(tmp_path, project_remote)
    env = base_env(tmp_path, org_remote)

    run([str(AR_NOTES), "init-org-notes", "--repo", str(org_remote)], env=env)
    run([str(AR_NOTES), "ensure-project-state", "--project-dir", str(project)], env=env)
    state = state_checkout(env)
    (state / ".agentic" / "notes" / "always-injected.md").write_text(
        "# Project Notes\n\nProject body.\n", encoding="utf-8"
    )
    (state / ".agentic" / "notes" / "evaluation.md").write_text(
        "# Evaluation\n\n", encoding="utf-8"
    )
    project_role = state / ".agentic" / "roles" / "gpu-kernel-engineer" / "notes"
    project_role.mkdir(parents=True, exist_ok=True)
    (project_role / "always-injected.md").write_text(
        "# Project GPU Role Notes\n\nProject role body.\n",
        encoding="utf-8",
    )
    (project_role / "benchmarking.md").write_text("# Project Benchmarking\n\n", encoding="utf-8")
    git(
        state,
        "add",
        ".agentic/notes/always-injected.md",
        ".agentic/notes/evaluation.md",
        ".agentic/roles/gpu-kernel-engineer/notes/always-injected.md",
        ".agentic/roles/gpu-kernel-engineer/notes/benchmarking.md",
    )
    git(state, "commit", "-m", "seed project notes")
    git(state, "push")

    (project / "AGENTS.md").write_text("# Existing Materialized File\n\n# Main Agent Body\n", encoding="utf-8")

    run(
        [
            str(AR_NOTES),
            "generate-instructions",
            "--project-dir",
            str(project),
            "--role",
            "gpu-kernel-engineer",
            "--tool",
            "codex",
        ],
        env=env,
    )

    text = (project / "AGENTS.md").read_text(encoding="utf-8")
    assert "# Main Agent Body" in text
    assert "Org body." in text
    assert "Role body." in text
    assert "Project body." in text
    assert "Project role body." in text
    assert "Org notes:" in text
    assert "Organization role notes: gpu-kernel-engineer" in text
    assert "Project notes:" in text
    assert "Project role notes: gpu-kernel-engineer" in text
    assert "  - triton.md" in text
    assert "  - pytorch.md" in text
    assert "  - kernel-optimization.md" in text
    assert "  - evaluation.md" in text
    assert "  - benchmarking.md" in text
    assert "  - always-injected.md" not in text


def test_replace_project_role_note_updates_shared_state_and_rendered_instructions(tmp_path: Path) -> None:
    project_remote = seed_project_remote(tmp_path)
    project = clone_project(tmp_path, project_remote)
    env = base_env(tmp_path)
    note_file = tmp_path / "research-coordinator-note.md"
    note_file.write_text(
        "# Research Coordinator Project Instructions\n\n"
        "**Goal:** Draft a sparse transformer paper.\n\n"
        "**Primary Metric:**\n"
        "- Name: validation loss\n"
        "- Direction: lower is better\n"
        "- Eval command: `uv run python eval.py`\n"
        "- Baseline: 1.23\n",
        encoding="utf-8",
    )

    run(
        [
            str(AR_NOTES),
            "replace-note",
            "--project-dir",
            str(project),
            "--scope",
            "project_role",
            "--role",
            "research-coordinator",
            "--note-name",
            "always-injected",
            "--note-file",
            str(note_file),
            "--refresh-parent",
            "--tool",
            "codex",
        ],
        env=env,
    )

    state = state_checkout(env)
    stored = (
        state / ".agentic" / "roles" / "research-coordinator" / "notes" / "always-injected.md"
    ).read_text(encoding="utf-8")
    rendered = (project / "AGENTS.md").read_text(encoding="utf-8")
    listed = run(
        [
            str(AR_NOTES),
            "list-notes",
            "--scope",
            "project_role",
            "--role",
            "research-coordinator",
            "--project-dir",
            str(project),
        ],
        env=env,
    )
    assert stored.startswith("# Research Coordinator Project Instructions")
    assert not (state / "AGENTS.md").exists()
    assert "**Goal:** Draft a sparse transformer paper." in rendered
    assert "validation loss" in stored
    assert "Project Role Notes: research-coordinator" in rendered
    assert "Directory:" in listed.stdout


def test_compaction_refresh_pulls_notes_and_rematerializes_instructions(tmp_path: Path) -> None:
    org_remote = seed_org_remote(tmp_path)
    project_remote = seed_project_remote(tmp_path)
    project = clone_project(tmp_path, project_remote)
    env = base_env(tmp_path, org_remote)

    run([str(AR_NOTES), "init-org-notes", "--repo", str(org_remote)], env=env)
    run([str(AR_NOTES), "ensure-project-state", "--project-dir", str(project)], env=env)
    state = state_checkout(env)
    (state / ".agentic" / "notes" / "always-injected.md").write_text(
        "# Project Notes\n\nOld project body.\n", encoding="utf-8"
    )
    git(state, "add", ".agentic/notes/always-injected.md")
    git(state, "commit", "-m", "seed old project note")
    git(state, "push")
    run(
        [
            str(AR_NOTES),
            "generate-instructions",
            "--project-dir",
            str(project),
            "--role",
            "gpu-kernel-engineer",
            "--tool",
            "codex",
        ],
        env=env,
    )
    assert "Old project body." in (project / "AGENTS.md").read_text(encoding="utf-8")
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    make_executable(fake_bin / "codex", "#!/bin/sh\nexit 0\n")
    env["PATH"] = f"{fake_bin}:{env['PATH']}"
    launch = run(
        [
            str(AGENTIC_RESEARCHER),
            "--sandbox", "none",
            "--tool",
            "codex",
            str(project),
        ],
        env=env,
    )
    assert launch.returncode == 0
    hook = project / ".codex" / "hooks" / "agentic-researcher-compaction.py"
    assert hook.exists()

    org_update = tmp_path / "org-update"
    run(["git", "clone", str(org_remote), str(org_update)])
    configure_git(org_update)
    (org_update / "notes" / "always-injected.md").write_text(
        "# Org Notes\n\nFresh org body.\n", encoding="utf-8"
    )
    git(org_update, "add", "notes/always-injected.md")
    git(org_update, "commit", "-m", "fresh org note")
    git(org_update, "push")

    state_update = tmp_path / "state-update"
    run(["git", "clone", str(project_remote), str(state_update)])
    configure_git(state_update)
    git(state_update, "fetch", "origin", "agentic/state")
    git(state_update, "checkout", "-B", "agentic/state", "origin/agentic/state")
    (state_update / ".agentic" / "notes" / "always-injected.md").write_text(
        "# Project Notes\n\nFresh project body.\n", encoding="utf-8"
    )
    git(state_update, "add", ".agentic/notes/always-injected.md")
    git(state_update, "commit", "-m", "fresh project note")
    git(state_update, "push", "origin", "agentic/state")

    result = run(
        [
            sys.executable,
            str(hook),
            str(project / "AGENTS.md"),
            str(AR_NOTES),
            str(project),
            "gpu-kernel-engineer",
            "codex",
        ],
        env=env,
        input='{"hook_event_name":"SessionStart"}',
    )

    payload = json.loads(result.stdout)
    text = (project / "AGENTS.md").read_text(encoding="utf-8")
    assert "Agentic Researcher refreshed post-compaction instructions." in payload["systemMessage"]
    assert "just experienced context compaction" in payload["hookSpecificOutput"]["additionalContext"]
    assert "Fresh org body." in text
    assert "Fresh project body." in text
    assert "Old project body." not in text


def test_note_updater_creates_new_org_note_and_commits(tmp_path: Path) -> None:
    org_remote = seed_org_remote(tmp_path)
    project = tmp_path / "project"
    project.mkdir()
    env = base_env(tmp_path, org_remote)
    run([str(AR_NOTES), "init-org-notes", "--repo", str(org_remote)], env=env)
    request = make_request(
        tmp_path,
        {
            "kind": "note_update_request",
            "target": {"scope": "org", "note_name": "git"},
            "summary": "Prefer named staging.",
            "lesson": "Stage files by explicit path instead of using git add all.",
            "source": {"user_id": "alice", "role_id": "gpu-kernel-engineer"},
        },
    )

    run([str(AR_NOTES), "update-note", "--request", str(request), "--project-dir", str(project)], env=env)

    checkout = org_checkout(env)
    assert "Stage files by explicit path" in (checkout / "notes" / "git.md").read_text()
    assert "notes: update notes/git.md" in git(checkout, "log", "-1", "--pretty=%s").stdout


def test_note_updater_does_not_duplicate_existing_role_bullet(tmp_path: Path) -> None:
    org_remote = seed_org_remote(tmp_path)
    project = tmp_path / "project"
    project.mkdir()
    env = base_env(tmp_path, org_remote)
    run([str(AR_NOTES), "init-org-notes", "--repo", str(org_remote)], env=env)
    checkout = org_checkout(env)
    note = checkout / "roles" / "gpu-kernel-engineer" / "notes" / "triton.md"
    note.write_text("# Triton\n\n## Lessons\n\n- Keep BLOCK power-of-two.\n", encoding="utf-8")
    git(checkout, "add", str(note.relative_to(checkout)))
    git(checkout, "commit", "-m", "seed role triton note")
    git(checkout, "push")
    request = make_request(
        tmp_path,
        {
            "kind": "note_update_request",
            "target": {"scope": "role", "role_id": "gpu-kernel-engineer", "note_name": "triton"},
            "summary": "Power-of-two blocks.",
            "lesson": "Keep BLOCK power-of-two.",
            "source": {"user_id": "alice", "role_id": "gpu-kernel-engineer"},
        },
    )

    run([str(AR_NOTES), "update-note", "--request", str(request), "--project-dir", str(project)], env=env)

    text = note.read_text(encoding="utf-8")
    assert text.count("Keep BLOCK power-of-two.") == 1


def test_note_updater_updates_project_note_on_agentic_state_branch(tmp_path: Path) -> None:
    project_remote = seed_project_remote(tmp_path)
    project = clone_project(tmp_path, project_remote)
    env = base_env(tmp_path)
    request = make_request(
        tmp_path,
        {
            "kind": "note_update_request",
            "target": {
                "scope": "project",
                "project_id": "sparse-transformer-2026",
                "note_name": "evaluation",
            },
            "summary": "Use fixed eval split.",
            "lesson": "Keep the evaluation split unchanged across experiments.",
            "source": {"user_id": "alice", "project_id": "sparse-transformer-2026"},
        },
    )

    run([str(AR_NOTES), "update-note", "--request", str(request), "--project-dir", str(project)], env=env)

    inspect = tmp_path / "inspect-state"
    run(["git", "clone", "-b", "agentic/state", str(project_remote), str(inspect)])
    assert "evaluation split unchanged" in (inspect / ".agentic" / "notes" / "evaluation.md").read_text()


def test_project_state_initialization_creates_required_layout(tmp_path: Path) -> None:
    project_remote = seed_project_remote(tmp_path)
    project = clone_project(tmp_path, project_remote)
    env = base_env(tmp_path)

    run([str(AR_NOTES), "ensure-project-state", "--project-dir", str(project)], env=env)

    state = state_checkout(env)
    assert (state / ".agentic" / "notes" / "always-injected.md").exists()
    assert (state / ".agentic" / "experiment-log" / "COUNTER.yaml").exists()
    assert (state / ".agentic" / "experiment-log" / "SUMMARY.md").exists()
    assert (state / ".agentic" / "experiment-log" / "experiments").is_dir()
    assert not (state / ".agentic" / "experiment-log" / "corrections").exists()
    assert not (state / "README.md").exists()
    head_with_parents = git(state, "rev-list", "--parents", "-n", "1", "HEAD").stdout.split()
    assert len(head_with_parents) == 1


def test_project_state_requires_project_id_when_no_remote_exists(tmp_path: Path) -> None:
    project = tmp_path / "project-without-remote"
    project.mkdir()
    env = base_env(tmp_path)
    env.pop("AR_PROJECT_ID", None)

    result = run(
        [str(AR_NOTES), "ensure-project-state", "--project-dir", str(project)],
        env=env,
        check=False,
    )

    assert result.returncode == 1
    assert "could not be inferred" in result.stderr


def test_project_state_infers_project_id_from_git_remote(tmp_path: Path) -> None:
    project_remote = seed_project_remote(tmp_path)
    project = clone_project(tmp_path, project_remote)
    env = base_env(tmp_path)
    env.pop("AR_PROJECT_ID", None)

    result = run(
        [str(AR_NOTES), "ensure-project-state", "--project-dir", str(project)],
        env=env,
        check=False,
    )

    assert result.returncode == 0
    projects = list((Path(env["AR_STATE_ROOT"]) / "projects").iterdir())
    assert len(projects) == 1
    assert projects[0].name == "project"
    assert (projects[0] / "agentic-state" / ".agentic" / "notes" / "always-injected.md").exists()


def test_project_remote_name_uses_repo_basename() -> None:
    loader = SourceFileLoader("ar_notes_project_remote_name_test", str(AR_NOTES))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    assert spec is not None
    ar_notes = importlib.util.module_from_spec(spec)
    loader.exec_module(ar_notes)

    assert ar_notes.project_remote_name("https://github.com/SmerkyG/abctest") == "abctest"
    assert ar_notes.project_remote_name("git@github.com:SmerkyG/abctest.git") == "abctest"
    assert ar_notes.project_remote_name("/tmp/abctest.git") == "abctest"


def test_update_note_refresh_parent_locks_org_and_parent_project(tmp_path: Path) -> None:
    request = make_request(
        tmp_path,
        {
            "kind": "note_update_request",
            "target": {"scope": "org", "note_name": "git"},
            "summary": "Lock test.",
            "lesson": "Lock test.",
        },
    )
    previous = {
        "AR_STATE_ROOT": os.environ.get("AR_STATE_ROOT"),
        "AR_PROJECT_ID": os.environ.get("AR_PROJECT_ID"),
        "AR_ORG_NOTES_REPO": os.environ.get("AR_ORG_NOTES_REPO"),
    }
    os.environ["AR_STATE_ROOT"] = str(tmp_path / "state")
    os.environ["AR_PROJECT_ID"] = "lock-project"
    os.environ["AR_ORG_NOTES_REPO"] = str(tmp_path / "org.git")
    try:
        loader = SourceFileLoader("ar_notes_lock_test", str(AR_NOTES))
        spec = importlib.util.spec_from_loader(loader.name, loader)
        assert spec is not None
        ar_notes = importlib.util.module_from_spec(spec)
        loader.exec_module(ar_notes)
        locks = ar_notes.lock_paths_for_args(
            SimpleNamespace(
                command="update-note",
                request=str(request),
                project_dir=str(tmp_path / "project"),
                refresh_parent=True,
            )
        )
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    lock_names = {path.name for path in locks}
    assert "org-agentic-notes.lock" in lock_names
    assert "project-lock-project.lock" in lock_names


def experiment_request(tmp_path: Path, short_description: str, key_result: str = "passed") -> Path:
    return make_request(
        tmp_path,
        {
            "kind": "experiment_result_request",
            "user_id": "alice",
            "short_description": short_description,
            "title": short_description,
            "description": "Test experiment.",
            "source": {"actor_id": "gpu-kernel-engineer", "role_id": "gpu-kernel-engineer"},
            "code": {"repo": "local", "branch": "test", "commit": "9f4d2a8c7b0e", "dirty": False},
            "command": "uv run pytest",
            "status": "completed",
            "key_result": key_result,
            "metrics": {"tests_passed": 1},
            "artifacts": {},
            "notes": "",
        },
    )


def summary_rows(summary: str) -> list[str]:
    return [line for line in summary.splitlines() if line.startswith("| [")]


def test_experiment_logger_creates_counter_ids_and_appends_summary(tmp_path: Path) -> None:
    project_remote = seed_project_remote(tmp_path)
    project = clone_project(tmp_path, project_remote)
    env = base_env(tmp_path)

    first = run(
        [
            str(AR_NOTES),
            "log-experiment",
            "--request",
            str(experiment_request(tmp_path, "Triton power-of-two shape test")),
            "--project-dir",
            str(project),
        ],
        env=env,
    ).stdout.strip()
    second = run(
        [
            str(AR_NOTES),
            "log-experiment",
            "--request",
            str(experiment_request(tmp_path, "Attention odd seq benchmark")),
            "--project-dir",
            str(project),
        ],
        env=env,
    ).stdout.strip()

    state = state_checkout(env)
    assert first == "E0001_alice_triton-power-of-two-shape-test"
    assert second == "E0002_alice_attention-odd-seq-benchmark"
    assert (state / ".agentic" / "experiment-log" / "experiments" / f"{first}.yaml").exists()
    assert (state / ".agentic" / "experiment-log" / "experiments" / f"{second}.yaml").exists()
    counter = yaml.safe_load((state / ".agentic" / "experiment-log" / "COUNTER.yaml").read_text())
    assert counter["next_experiment_number"] == 3
    assert "next_correction_number" not in counter
    summary = (state / ".agentic" / "experiment-log" / "SUMMARY.md").read_text()
    assert len(summary_rows(summary)) == 2
    assert first in summary
    assert second in summary


def test_summary_is_append_only_and_existing_experiment_files_are_unchanged(tmp_path: Path) -> None:
    project_remote = seed_project_remote(tmp_path)
    project = clone_project(tmp_path, project_remote)
    env = base_env(tmp_path)
    first = run(
        [
            str(AR_NOTES),
            "log-experiment",
            "--request",
            str(experiment_request(tmp_path, "First run")),
            "--project-dir",
            str(project),
        ],
        env=env,
    ).stdout.strip()
    state = state_checkout(env)
    first_file = state / ".agentic" / "experiment-log" / "experiments" / f"{first}.yaml"
    first_content = first_file.read_text(encoding="utf-8")
    hidden = state / ".agentic" / "experiment-log" / "experiments" / "E9999_alice_hidden.yaml"
    hidden.write_text("kind: experiment_result\nexperiment_id: E9999_alice_hidden\n", encoding="utf-8")
    git(state, "add", str(hidden.relative_to(state)))
    git(state, "commit", "-m", "add hidden experiment")
    git(state, "push")

    second = run(
        [
            str(AR_NOTES),
            "log-experiment",
            "--request",
            str(experiment_request(tmp_path, "Second run")),
            "--project-dir",
            str(project),
        ],
        env=env,
    ).stdout.strip()

    summary = (state / ".agentic" / "experiment-log" / "SUMMARY.md").read_text()
    assert first_file.read_text(encoding="utf-8") == first_content
    assert second in summary
    assert "E9999_alice_hidden" not in summary


def test_push_conflict_retries_with_next_counter_number(tmp_path: Path) -> None:
    project_remote = seed_project_remote(tmp_path)
    project_one = clone_project(tmp_path, project_remote, "project-one")
    project_two = clone_project(tmp_path, project_remote, "project-two")
    env_one = base_env(tmp_path / "one")
    env_two = base_env(tmp_path / "two")
    env_one["AR_PROJECT_ID"] = "conflict-project"
    env_two["AR_PROJECT_ID"] = "conflict-project"

    run([str(AR_NOTES), "ensure-project-state", "--project-dir", str(project_one)], env=env_one)
    run([str(AR_NOTES), "ensure-project-state", "--project-dir", str(project_two)], env=env_two)
    state_two = state_checkout(env_two, "conflict-project")
    waiting = tmp_path / "waiting"
    allow = tmp_path / "allow"
    hook = state_two / ".git" / "hooks" / "pre-push"
    hook.write_text(
        "#!/bin/sh\n"
        f"touch '{waiting}'\n"
        f"while [ ! -f '{allow}' ]; do sleep 0.05; done\n",
        encoding="utf-8",
    )
    hook.chmod(hook.stat().st_mode | stat.S_IXUSR)

    proc_two = subprocess.Popen(
        [
            str(AR_NOTES),
            "log-experiment",
            "--request",
            str(experiment_request(tmp_path, "Conflict loser")),
            "--project-dir",
            str(project_two),
        ],
        cwd=REPO_ROOT,
        env=env_two,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    for _ in range(100):
        if waiting.exists():
            break
        time.sleep(0.05)
    assert waiting.exists()
    winner = run(
        [
            str(AR_NOTES),
            "log-experiment",
            "--request",
            str(experiment_request(tmp_path, "Conflict winner")),
            "--project-dir",
            str(project_one),
        ],
        env=env_one,
    ).stdout.strip()
    allow.touch()
    stdout, stderr = proc_two.communicate(timeout=30)
    assert proc_two.returncode == 0, stderr
    loser = stdout.strip()
    assert winner.startswith("E0001_")
    assert loser.startswith("E0002_")


def test_same_installation_multiple_actor_worktrees_serialize_project_log_updates(tmp_path: Path) -> None:
    project_remote = seed_project_remote(tmp_path)
    project_one = clone_project(tmp_path, project_remote, "actor-one")
    project_two = clone_project(tmp_path, project_remote, "actor-two")
    env = base_env(tmp_path)
    env["AR_PROJECT_ID"] = "shared-worktree-project"

    run([str(AR_NOTES), "ensure-project-state", "--project-dir", str(project_one)], env=env)
    state = state_checkout(env, "shared-worktree-project")
    waiting = tmp_path / "same-install-waiting"
    allow = tmp_path / "same-install-allow"
    hook = state / ".git" / "hooks" / "pre-push"
    hook.write_text(
        "#!/bin/sh\n"
        f"touch '{waiting}'\n"
        f"while [ ! -f '{allow}' ]; do sleep 0.05; done\n",
        encoding="utf-8",
    )
    hook.chmod(hook.stat().st_mode | stat.S_IXUSR)

    proc_one = subprocess.Popen(
        [
            str(AR_NOTES),
            "log-experiment",
            "--request",
            str(experiment_request(tmp_path, "Shared state first")),
            "--project-dir",
            str(project_one),
        ],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    for _ in range(100):
        if waiting.exists():
            break
        time.sleep(0.05)
    assert waiting.exists()

    proc_two = subprocess.Popen(
        [
            str(AR_NOTES),
            "log-experiment",
            "--request",
            str(experiment_request(tmp_path, "Shared state second")),
            "--project-dir",
            str(project_two),
        ],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    allow.touch()
    stdout_one, stderr_one = proc_one.communicate(timeout=30)
    stdout_two, stderr_two = proc_two.communicate(timeout=30)
    assert proc_one.returncode == 0, stderr_one
    assert proc_two.returncode == 0, stderr_two
    assert stdout_one.strip().startswith("E0001_")
    assert stdout_two.strip().startswith("E0002_")
    summary = (state / ".agentic" / "experiment-log" / "SUMMARY.md").read_text()
    assert len(summary_rows(summary)) == 2


def test_correction_logging_appends_to_experiment_file_and_summary_row(tmp_path: Path) -> None:
    project_remote = seed_project_remote(tmp_path)
    project = clone_project(tmp_path, project_remote)
    env = base_env(tmp_path)
    experiment_id = run(
        [
            str(AR_NOTES),
            "log-experiment",
            "--request",
            str(experiment_request(tmp_path, "Needs correction")),
            "--project-dir",
            str(project),
        ],
        env=env,
    ).stdout.strip()
    correction_request = make_request(
        tmp_path,
        {
            "kind": "experiment_correction_request",
            "experiment_id": experiment_id,
            "user_id": "alice",
            "summary": "Metric was computed on the wrong split.",
            "correction": "Use the fixed validation split.",
        },
    )

    correction_id = run(
        [
            str(AR_NOTES),
            "log-correction",
            "--request",
            str(correction_request),
            "--project-dir",
            str(project),
        ],
        env=env,
    ).stdout.strip()
    second_request = make_request(
        tmp_path,
        {
            "kind": "experiment_correction_request",
            "experiment_id": experiment_id,
            "user_id": "alice",
            "summary": "Artifact path was stale.",
            "correction": "Use the artifact path from the rerun.",
        },
    )
    second_correction_id = run(
        [
            str(AR_NOTES),
            "log-correction",
            "--request",
            str(second_request),
            "--project-dir",
            str(project),
        ],
        env=env,
    ).stdout.strip()

    state = state_checkout(env)
    experiment_path = state / ".agentic" / "experiment-log" / "experiments" / f"{experiment_id}.yaml"
    experiment_doc = yaml.safe_load(experiment_path.read_text())
    assert correction_id == "E0001_R001"
    assert second_correction_id == "E0001_R002"
    assert [entry["correction_id"] for entry in experiment_doc["corrections"]] == [
        correction_id,
        second_correction_id,
    ]
    assert experiment_doc["corrections"][0]["correction"] == "Use the fixed validation split."
    assert not (state / ".agentic" / "experiment-log" / "corrections").exists()
    summary = (state / ".agentic" / "experiment-log" / "SUMMARY.md").read_text()
    assert correction_id in summary
    assert second_correction_id in summary
    assert f"experiments/{experiment_id}.yaml" in summary


def make_executable(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def test_launcher_notes_integration_keeps_builtin_skill_rendering(tmp_path: Path) -> None:
    org_remote = seed_org_remote(tmp_path)
    project_remote = seed_project_remote(tmp_path)
    project = clone_project(tmp_path, project_remote)
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    make_executable(fake_bin / "codex", "#!/bin/sh\nexit 0\n")
    env = base_env(tmp_path, org_remote)
    env["PATH"] = f"{fake_bin}:{env['PATH']}"
    stale_skill = project / ".agents" / "skills" / "experiment_log" / "SKILL.md"
    stale_skill.parent.mkdir(parents=True)
    stale_skill.write_text(
        "<!-- Generated by agentic-researcher. Edit the source skill to change this file. -->\n",
        encoding="utf-8",
    )

    result = run(
        [
            str(AGENTIC_RESEARCHER),
            "--sandbox", "none",
            "--tool",
            "codex",
            str(project),
        ],
        env=env,
    )

    assert result.returncode == 0
    assert (project / ".agents" / "skills" / "setup_research_plan" / "SKILL.md").exists()
    assert not (project / ".agents" / "skills" / "note_usage" / "SKILL.md").exists()
    assert not (project / ".agents" / "skills" / "experiment_log" / "SKILL.md").exists()
    assert (project / ".codex" / "agents" / "note-updater.toml").exists()
    assert (project / ".codex" / "agents" / "experiment-logger.toml").exists()
    assert not (project / ".codex" / "agents" / "research-coordinator.toml").exists()
    instruction_text = (project / "AGENTS.md").read_text(encoding="utf-8")
    assert "<!-- AGENTIC-RESEARCHER-MAIN-AGENT-START name=research-coordinator -->" in instruction_text
    assert "# Research Coordinator Instructions" in instruction_text
    assert "### Agentic Notes" in instruction_text
    assert "## Agentic Notes" in instruction_text
    assert "Org body." in instruction_text


def test_launcher_renders_org_agents_and_overrides_builtin_agents(tmp_path: Path) -> None:
    org_remote = init_bare_remote(
        tmp_path,
        "org-agent-extensions",
        {
            "notes/always-injected.md": "# Org Notes\n\nOrg body.\n",
            "agents/experiment-runner.md": (
                "---\n"
                "name: experiment-runner\n"
                "kind: subagent\n"
                "description: Org-specific experiment runner.\n"
                "codex_reasoning_effort: low\n"
                "---\n\n"
                "You are the org-specific experiment runner.\n"
            ),
            "agents/data-curator.md": (
                "---\n"
                "name: data-curator\n"
                "kind: subagent\n"
                "description: Inspect datasets and splits.\n"
                "codex_reasoning_effort: medium\n"
                "---\n\n"
                "You are the org data curator.\n"
            ),
            "roles/data-curator/notes/always-injected.md": (
                "# Data Curator Role\n\nUse the org dataset checklist.\n"
            ),
        },
    )
    project_remote = seed_project_remote(tmp_path)
    project = clone_project(tmp_path, project_remote)
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    make_executable(fake_bin / "codex", "#!/bin/sh\nexit 0\n")
    env = base_env(tmp_path, org_remote)
    env["PATH"] = f"{fake_bin}:{env['PATH']}"

    run(
        [
            str(AGENTIC_RESEARCHER),
            "--sandbox",
            "none",
            "--tool",
            "codex",
            str(project),
        ],
        env=env,
    )

    experiment_runner = project / ".codex" / "agents" / "experiment-runner.toml"
    data_curator = project / ".codex" / "agents" / "data-curator.toml"
    assert experiment_runner.exists()
    assert data_curator.exists()
    experiment_text = experiment_runner.read_text(encoding="utf-8")
    data_curator_text = data_curator.read_text(encoding="utf-8")
    assert "Org-specific experiment runner" in experiment_text
    assert "You are the org-specific experiment runner." in experiment_text
    assert 'model_reasoning_effort = "low"' in experiment_text
    assert "Run one clearly scoped experiment at a time." not in experiment_text
    assert "You are the org data curator." in data_curator_text
    assert "Use the org dataset checklist." in data_curator_text


def test_launcher_renders_org_main_agent_override_without_subagent(tmp_path: Path) -> None:
    org_remote = init_bare_remote(
        tmp_path,
        "org-main-agents",
        {
            "agents/research-coordinator.md": (
                "---\n"
                "name: research-coordinator\n"
                "kind: main\n"
                "description: Org research coordinator.\n"
                "codex_reasoning_effort: high\n"
                "---\n\n"
                "# Org Research Coordinator\n\n"
                "Use the org-specific research playbook.\n"
            ),
            "roles/research-coordinator/notes/always-injected.md": (
                "# Coordinator Role Notes\n\nUse the org coordinator note.\n"
            ),
        },
    )
    project_remote = seed_project_remote(tmp_path)
    project = clone_project(tmp_path, project_remote)
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    make_executable(fake_bin / "codex", "#!/bin/sh\nexit 0\n")
    env = base_env(tmp_path, org_remote)
    env["PATH"] = f"{fake_bin}:{env['PATH']}"

    result = run(
        [
            str(AGENTIC_RESEARCHER),
            "--sandbox",
            "none",
            "--tool",
            "codex",
            str(project),
        ],
        env=env,
    )

    assert result.returncode == 0, result.stderr
    instruction_text = (project / "AGENTS.md").read_text(encoding="utf-8")
    assert "# Org Research Coordinator" in instruction_text
    assert "Use the org-specific research playbook." in instruction_text
    assert "# Research Coordinator Instructions" not in instruction_text
    assert "Use the org coordinator note." in instruction_text
    assert not (project / ".codex" / "agents" / "research-coordinator.toml").exists()


def test_multiple_main_agents_use_separate_worktrees_and_project_role_notes(tmp_path: Path) -> None:
    org_remote = init_bare_remote(
        tmp_path,
        "org-paper-agent",
        {
            "agents/research-paper-author.md": (
                "---\n"
                "name: research-paper-author\n"
                "kind: main\n"
                "description: Draft papers from verified evidence.\n"
                "codex_reasoning_effort: high\n"
                "---\n\n"
                "# Research Paper Author Instructions\n\n"
                "Write from verified experiment logs and project role notes.\n"
            ),
        },
    )
    project_remote = seed_project_remote(tmp_path)
    coordinator = clone_project(tmp_path, project_remote, name="project-coordinator")
    paper = tmp_path / "project-paper"
    run(["git", "-C", str(coordinator), "worktree", "add", "-b", "paper-draft", str(paper), "HEAD"])
    configure_git(paper)

    env = base_env(tmp_path, org_remote)
    coordinator_note = tmp_path / "coordinator-note.md"
    coordinator_note.write_text(
        "# Research Coordinator Project Instructions\n\n"
        "Coordinator goal: run verified experiments.\n",
        encoding="utf-8",
    )
    paper_note = tmp_path / "paper-note.md"
    paper_note.write_text(
        "# Research Paper Author Project Instructions\n\n"
        "Paper goal: write the manuscript from verified evidence.\n",
        encoding="utf-8",
    )
    for role, note in (
        ("research-coordinator", coordinator_note),
        ("research-paper-author", paper_note),
    ):
        run(
            [
                str(AR_NOTES),
                "replace-note",
                "--project-dir",
                str(coordinator),
                "--scope",
                "project_role",
                "--role",
                role,
                "--note-name",
                "always-injected",
                "--note-file",
                str(note),
            ],
            env=env,
        )

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    make_executable(fake_bin / "codex", "#!/bin/sh\nexit 0\n")
    env["PATH"] = f"{fake_bin}:{env['PATH']}"

    coordinator_launch = run(
        [
            str(AGENTIC_RESEARCHER),
            "--sandbox",
            "none",
            "--tool",
            "codex",
            "--main-agent",
            "research-coordinator",
            str(coordinator),
        ],
        env=env,
    )
    paper_launch = run(
        [
            str(AGENTIC_RESEARCHER),
            "--sandbox",
            "none",
            "--tool",
            "codex",
            "--main-agent",
            "research-paper-author",
            str(paper),
        ],
        env=env,
    )

    assert coordinator_launch.returncode == 0, coordinator_launch.stderr
    assert paper_launch.returncode == 0, paper_launch.stderr
    coordinator_text = (coordinator / "AGENTS.md").read_text(encoding="utf-8")
    paper_text = (paper / "AGENTS.md").read_text(encoding="utf-8")
    assert "# Research Coordinator Instructions" in coordinator_text
    assert "# Research Paper Author Instructions" not in coordinator_text
    assert "# Research Paper Author Instructions" in paper_text
    assert "# Research Coordinator Instructions" not in paper_text
    assert "Coordinator goal: run verified experiments." in coordinator_text
    assert "Paper goal: write the manuscript" not in coordinator_text
    assert "Paper goal: write the manuscript from verified evidence." in paper_text
    assert "Coordinator goal: run verified experiments." not in paper_text
    state = state_checkout(env)
    assert (state / ".agentic" / "roles" / "research-coordinator" / "notes" / "always-injected.md").exists()
    assert (state / ".agentic" / "roles" / "research-paper-author" / "notes" / "always-injected.md").exists()
    assert not (state / "AGENTS.md").exists()


def test_org_main_agent_name_conflict_removes_builtin_subagent(tmp_path: Path) -> None:
    org_remote = init_bare_remote(
        tmp_path,
        "org-main-conflict",
        {
            "agents/experiment-runner.md": (
                "---\n"
                "name: experiment-runner\n"
                "kind: main\n"
                "description: Not a subagent in this org.\n"
                "---\n\n"
                "This definition intentionally claims the built-in subagent name.\n"
            ),
        },
    )
    project_remote = seed_project_remote(tmp_path)
    project = clone_project(tmp_path, project_remote)
    stale_agent = project / ".codex" / "agents" / "experiment-runner.toml"
    stale_agent.parent.mkdir(parents=True)
    stale_agent.write_text(
        "<!-- Generated by agentic-researcher. Edit the source agent definition to change this agent. -->\n",
        encoding="utf-8",
    )
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    make_executable(fake_bin / "codex", "#!/bin/sh\nexit 0\n")
    env = base_env(tmp_path, org_remote)
    env["PATH"] = f"{fake_bin}:{env['PATH']}"

    result = run(
        [
            str(AGENTIC_RESEARCHER),
            "--sandbox",
            "none",
            "--tool",
            "codex",
            str(project),
        ],
        env=env,
    )

    assert result.returncode == 0, result.stderr
    assert not stale_agent.exists()
