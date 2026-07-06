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
AGENTIC_NOTES_INTERNAL = REPO_ROOT / "capabilities" / "agentic-notes" / "lib" / "agentic-notes-internal"
AGENTIC_NOTES = REPO_ROOT / "capabilities" / "agentic-notes" / "bin" / "agentic-notes"
EXPERIMENT_LOG = REPO_ROOT / "capabilities" / "experiment-log" / "bin" / "experiment-log"
AGENTIC_TEAM = REPO_ROOT / "agentic-team"
AGENTIC_WORKSPACE = REPO_ROOT / "scripts" / "bin" / "agentic-workspace"


def test_builtin_subagents_have_one_contract_template() -> None:
    for agent_path in sorted((REPO_ROOT / "agents").glob("*.md")):
        text = agent_path.read_text(encoding="utf-8")
        if "kind: subagent" not in text:
            continue
        assert "## Subagent Contract" in text, agent_path.name
        contract = text.split("## Subagent Contract", 1)[1]
        if "\n## " in contract:
            contract = contract.split("\n## ", 1)[0]
        assert "Use when:" in contract, agent_path.name
        assert "Request template:" in contract, agent_path.name
        assert contract.count("```yaml") == 1, agent_path.name
        assert "\nkind:" not in contract, agent_path.name
        assert "Request kind:" not in contract, agent_path.name


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


def write_pre_push_hook(repo: Path, content: str) -> Path:
    hook_dir = repo / ".git-hooks"
    hook_dir.mkdir(parents=True, exist_ok=True)
    git(repo, "config", "extensions.worktreeConfig", "true")
    git(repo, "config", "--worktree", "core.hooksPath", str(hook_dir))
    hook = hook_dir / "pre-push"
    hook.write_text(content, encoding="utf-8")
    hook.chmod(hook.stat().st_mode | stat.S_IXUSR)
    return hook


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
    git(project, "checkout", "-b", "kernel-search")
    return project


def base_env(tmp_path: Path, org_remote: Path | None = None) -> dict[str, str]:
    env = os.environ.copy()
    env["PATH"] = (
        f"{REPO_ROOT / 'scripts' / 'bin'}:"
        f"{REPO_ROOT / 'capabilities' / 'agentic-notes' / 'bin'}:"
        f"{REPO_ROOT / 'capabilities' / 'experiment-log' / 'bin'}:"
        f"{env['PATH']}"
    )
    env.update(
        {
            "AR_STATE_ROOT": str(tmp_path / "state"),
            "AR_MAIN_AGENT": "research-coordinator",
            "AR_WORK_BRANCH": "kernel-search",
            "AR_USER_ID": "alice",
            "AR_PROJECT_STATE_BRANCH": "agentic/project-state",
            "AR_CAPABILITIES": "agentic-notes,experiment-log",
            "AR_NOTES_GIT_NAME": "Agentic Test",
            "AR_NOTES_GIT_EMAIL": "agentic-test@example.com",
            "AR_NOTES_AUTO_REFRESH": "false",
            "UV_CACHE_DIR": str(REPO_ROOT / ".pytest_cache" / "uv" / "cache"),
            "UV_PYTHON_INSTALL_DIR": str(REPO_ROOT / ".pytest_cache" / "uv" / "python"),
            "UV_TOOL_DIR": str(REPO_ROOT / ".pytest_cache" / "uv" / "tools"),
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


def state_checkout(env: dict[str, str], workspace_name: str = "project") -> Path:
    return workspace_root(env, workspace_name) / "project-state"


def workspace_root(env: dict[str, str], workspace_name: str = "project") -> Path:
    configured = env.get("AR_WORKSPACE_ROOT")
    if configured:
        return Path(configured)
    return Path(env["AR_STATE_ROOT"]).parent / f"{workspace_name}-at"


def work_name(work_branch: str) -> str:
    return work_branch.rstrip("/").split("/")[-1]


def work_state_checkout(
    env: dict[str, str],
    workspace_name: str = "project",
    work_branch: str = "kernel-search",
) -> Path:
    return workspace_root(env, workspace_name) / work_name(work_branch) / "state"


def work_log(env: dict[str, str], workspace_name: str = "project", work_branch: str = "kernel-search") -> Path:
    return work_state_checkout(env, workspace_name, work_branch) / "experiment-log"


def work_state_dir(env: dict[str, str], workspace_name: str = "project", work_branch: str = "kernel-search") -> Path:
    return work_state_checkout(env, workspace_name, work_branch)


def at_launch_args(
    project: Path,
    env: dict[str, str],
    work_name_value: str = "kernel-search",
    source_ref: str = "kernel-search",
) -> list[str]:
    return [
        str(workspace_root(env)),
        work_name_value,
        "--from",
        source_ref,
        "--project-dir",
        str(project),
        "--branch",
        source_ref,
    ]


def assert_linked_worktree(path: Path) -> None:
    assert (path / ".git").is_file(), f"{path} should be a linked Git worktree"


def local_experiment_id(ref: str) -> str:
    return ref.split("::", 1)[1] if "::" in ref else ref


def org_checkout(env: dict[str, str]) -> Path:
    return Path(env["AR_STATE_ROOT"]) / "repos" / "org-agentic-notes"


def seed_org_remote(tmp_path: Path) -> Path:
    return init_bare_remote(
        tmp_path,
        "org-notes",
        {
            "agent-notes/all-agents/always-injected.md": "# Org Notes\n\nOrg body.\n",
            "agent-notes/all-agents/triton.md": "# Triton\n\nTopic hints: triton, launch checks\n\nUse Triton-specific launch checks.\n",
            "agent-notes/all-agents/pytorch.md": "# PyTorch\n\nTopic hints: pytorch, launch checks\n\nUse PyTorch-specific launch checks.\n",
            "agent-notes/gpu-kernel-engineer/always-injected.md": "# Agent Type Notes\n\nAgent Type body.\n",
            "agent-notes/gpu-kernel-engineer/kernel-optimization.md": "# Kernel Optimization\n\nTopic hints: occupancy, kernels\n\nUse occupancy checks.\n",
        },
    )


def seed_project_remote(tmp_path: Path) -> Path:
    return init_bare_remote(tmp_path, "project", {"README.md": "# Project\n"})


def test_generate_instruction_injects_always_injected_notes_and_lists_on_demand_notes(tmp_path: Path) -> None:
    org_remote = seed_org_remote(tmp_path)
    project_remote = seed_project_remote(tmp_path)
    project = clone_project(tmp_path, project_remote)
    env = base_env(tmp_path, org_remote)

    run([str(AGENTIC_NOTES_INTERNAL), "init-org-notes", "--repo", str(org_remote)], env=env)
    run([str(AGENTIC_NOTES_INTERNAL), "ensure-project-state", "--project-dir", str(project)], env=env)
    state = state_checkout(env)
    assert_linked_worktree(state)
    (state / "agent-notes" / "all-agents" / "always-injected.md").write_text(
        "# Project Notes\n\nProject body.\n", encoding="utf-8"
    )
    (state / "agent-notes" / "all-agents" / "evaluation.md").write_text(
        "# Evaluation\n\nTopic hints: eval command, fixed split\n\nUse the fixed evaluation command.\n", encoding="utf-8"
    )
    project_agent = state / "agent-notes" / "gpu-kernel-engineer"
    project_agent.mkdir(parents=True, exist_ok=True)
    (project_agent / "always-injected.md").write_text(
        "# Project GPU Agent Type Notes\n\nProject agent type body.\n",
        encoding="utf-8",
    )
    (project_agent / "benchmarking.md").write_text(
        "# Project Benchmarking\n\nTopic hints: benchmark scripts\n\nUse project benchmark scripts.\n", encoding="utf-8"
    )
    git(
        state,
        "add",
        "agent-notes/all-agents/always-injected.md",
        "agent-notes/all-agents/evaluation.md",
        "agent-notes/gpu-kernel-engineer/always-injected.md",
        "agent-notes/gpu-kernel-engineer/benchmarking.md",
    )
    git(state, "commit", "-m", "seed project state")
    git(state, "push")

    (project / "AGENTS.md").write_text("# Existing Materialized File\n\n# Main Agent Body\n", encoding="utf-8")

    run(
        [
            str(AGENTIC_NOTES_INTERNAL),
            "generate-instructions",
            "--project-dir",
            str(project),
            "--agent-type",
            "gpu-kernel-engineer",
            "--cli",
            "codex",
        ],
        env=env,
    )

    text = (project / "AGENTS.md").read_text(encoding="utf-8")
    assert "# Main Agent Body" in text
    assert "Org body." in text
    assert "Agent Type body." in text
    assert "Project body." in text
    assert "Project agent type body." in text
    assert "Source:" not in text
    assert "Directory:" not in text
    assert "(none)" not in text
    assert "### Available On-Demand Note Topics" in text
    assert "--agent-type gpu-kernel-engineer NOTE_TOPIC" in text
    assert "- `triton` - triton, launch checks" in text
    assert "- `pytorch` - pytorch, launch checks" in text
    assert "- `kernel-optimization` - occupancy, kernels" in text
    assert "- `evaluation` - eval command, fixed split" in text
    assert "- `benchmarking` - benchmark scripts" in text
    assert "- `always-injected`" not in text

    rendered_note = run(
        [
            str(AGENTIC_NOTES),
            "read-note",
            "--project-dir",
            str(project),
            "--agent-type",
            "gpu-kernel-engineer",
            "benchmarking",
        ],
        env=env,
    ).stdout
    assert "# Agentic Note: benchmarking" in rendered_note
    assert "## Project: gpu-kernel-engineer" in rendered_note
    assert "Use project benchmark scripts." in rendered_note
    assert "# Project Benchmarking" not in rendered_note
    assert "Source:" not in rendered_note


def test_generate_instruction_skips_title_only_placeholder_notes(tmp_path: Path) -> None:
    project_remote = seed_project_remote(tmp_path)
    project = clone_project(tmp_path, project_remote)
    env = base_env(tmp_path)

    run([str(AGENTIC_NOTES_INTERNAL), "ensure-project-state", "--project-dir", str(project)], env=env)
    (project / "AGENTS.md").write_text("# Existing Materialized File\n", encoding="utf-8")

    run(
        [
            str(AGENTIC_NOTES_INTERNAL),
            "generate-instructions",
            "--project-dir",
            str(project),
            "--agent-type",
            "research-coordinator",
            "--cli",
            "codex",
        ],
        env=env,
    )

    text = (project / "AGENTS.md").read_text(encoding="utf-8")
    assert "### Always-Injected Notes" not in text
    assert "Project All Agents Notes" not in text
    assert "### Available On-Demand Note Topics" not in text


def test_render_sections_batches_multiple_agent_note_sections(tmp_path: Path) -> None:
    org_remote = seed_org_remote(tmp_path)
    project_remote = seed_project_remote(tmp_path)
    project = clone_project(tmp_path, project_remote)
    env = base_env(tmp_path, org_remote)

    run([str(AGENTIC_NOTES_INTERNAL), "init-org-notes", "--repo", str(org_remote)], env=env)
    run([str(AGENTIC_NOTES_INTERNAL), "ensure-project-state", "--project-dir", str(project)], env=env)
    output_dir = tmp_path / "rendered-notes"

    run(
        [
            str(AGENTIC_NOTES_INTERNAL),
            "render-sections",
            "--project-dir",
            str(project),
            "--output-dir",
            str(output_dir),
            "--agent-type",
            "gpu-kernel-engineer",
            "--agent-type",
            "research-coordinator",
        ],
        env=env,
    )

    gpu_text = (output_dir / "gpu-kernel-engineer.md").read_text(encoding="utf-8")
    coordinator_text = (output_dir / "research-coordinator.md").read_text(encoding="utf-8")
    assert "Org body." in gpu_text
    assert "Agent Type body." in gpu_text
    assert "#### Organization: gpu-kernel-engineer" in gpu_text
    assert "Org body." in coordinator_text
    assert "Organization: research-coordinator" not in coordinator_text


def test_read_note_combines_all_scoped_note_parts(tmp_path: Path) -> None:
    org_remote = seed_org_remote(tmp_path)
    project_remote = seed_project_remote(tmp_path)
    project = clone_project(tmp_path, project_remote)
    env = base_env(tmp_path, org_remote)

    run([str(AGENTIC_NOTES_INTERNAL), "init-org-notes", "--repo", str(org_remote)], env=env)
    run([str(AGENTIC_NOTES_INTERNAL), "ensure-project-state", "--project-dir", str(project)], env=env)

    org = org_checkout(env)
    configure_git(org)
    (org / "agent-notes" / "gpu-kernel-engineer" / "triton.md").write_text(
        "# Org GPU Triton\n\nOrg agent type body.\n",
        encoding="utf-8",
    )
    git(org, "add", "agent-notes/gpu-kernel-engineer/triton.md")
    git(org, "commit", "-m", "seed org agent triton")

    state = state_checkout(env)
    (state / "agent-notes" / "all-agents" / "triton.md").write_text(
        "# Project Triton\n\nProject all agents body.\n",
        encoding="utf-8",
    )
    project_agent = state / "agent-notes" / "gpu-kernel-engineer"
    project_agent.mkdir(parents=True, exist_ok=True)
    (project_agent / "triton.md").write_text(
        "# Project GPU Triton\n\nProject agent type body.\n",
        encoding="utf-8",
    )
    git(
        state,
        "add",
        "agent-notes/all-agents/triton.md",
        "agent-notes/gpu-kernel-engineer/triton.md",
    )
    git(state, "commit", "-m", "seed project triton")

    result = run(
        [
            str(AGENTIC_NOTES),
            "read-note",
            "--project-dir",
            str(project),
            "--agent-type",
            "gpu-kernel-engineer",
            "triton",
        ],
        env=env,
    )

    rendered = result.stdout
    expected_order = [
        "## Organization: all agents",
        "Use Triton-specific launch checks.",
        "## Organization: gpu-kernel-engineer",
        "Org agent type body.",
        "## Project: all agents",
        "Project all agents body.",
        "## Project: gpu-kernel-engineer",
        "Project agent type body.",
    ]
    positions = [rendered.index(item) for item in expected_order]
    assert positions == sorted(positions)
    assert "Org agent type body." in rendered
    assert "Project all agents body." in rendered
    assert "Project agent type body." in rendered
    assert "# Triton" not in rendered
    assert "# Org GPU Triton" not in rendered
    assert "# Project Triton" not in rendered
    assert "# Project GPU Triton" not in rendered
    assert "Source:" not in rendered
    assert "Directory:" not in rendered


def test_refresh_loop_pulls_org_notes_while_heartbeat_is_active(tmp_path: Path) -> None:
    org_remote = seed_org_remote(tmp_path)
    project_remote = seed_project_remote(tmp_path)
    project = clone_project(tmp_path, project_remote)
    env = base_env(tmp_path, org_remote)

    run([str(AGENTIC_NOTES_INTERNAL), "init-org-notes", "--repo", str(org_remote)], env=env)
    run([str(AGENTIC_NOTES_INTERNAL), "ensure-project-state", "--project-dir", str(project)], env=env)

    org_update = tmp_path / "org-update"
    run(["git", "clone", str(org_remote), str(org_update)])
    configure_git(org_update)
    (org_update / "agent-notes" / "all-agents" / "always-injected.md").write_text(
        "# Org Notes\n\nPulled by refresh loop.\n",
        encoding="utf-8",
    )
    git(org_update, "add", "agent-notes/all-agents/always-injected.md")
    git(org_update, "commit", "-m", "update org notes")
    git(org_update, "push")

    heartbeat_dir = tmp_path / "heartbeats"
    heartbeat_dir.mkdir()
    heartbeat = heartbeat_dir / "agent.heartbeat"
    heartbeat.touch()
    proc = subprocess.Popen(
        [
            str(AGENTIC_NOTES_INTERNAL),
            "refresh-loop",
            "--project-dir",
            str(project),
            "--heartbeat-dir",
            str(heartbeat_dir),
            "--interval-seconds",
            "1",
            "--stale-seconds",
            "3",
        ],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        note_path = org_checkout(env) / "agent-notes" / "all-agents" / "always-injected.md"
        deadline = time.time() + 8
        while time.time() < deadline:
            heartbeat.touch()
            if "Pulled by refresh loop." in note_path.read_text(encoding="utf-8"):
                break
            time.sleep(0.25)
        else:
            stdout, stderr = proc.communicate(timeout=1)
            raise AssertionError(f"refresh loop did not pull org update\nSTDOUT:\n{stdout}\nSTDERR:\n{stderr}")
    finally:
        heartbeat.unlink(missing_ok=True)
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.terminate()
            proc.wait(timeout=5)


def test_replace_project_agent_note_updates_shared_state_and_rendered_instructions(tmp_path: Path) -> None:
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
            str(AGENTIC_NOTES_INTERNAL),
            "replace-note",
            "--project-dir",
            str(project),
            "--scope",
            "project",
            "--agent-type",
            "research-coordinator",
            "--note-name",
            "always-injected",
            "--note-file",
            str(note_file),
            "--refresh-parent",
            "--cli",
            "codex",
        ],
        env=env,
    )

    state = state_checkout(env)
    stored = (
        state / "agent-notes" / "research-coordinator" / "always-injected.md"
    ).read_text(encoding="utf-8")
    rendered = (project / "AGENTS.md").read_text(encoding="utf-8")
    listed = run(
        [
            str(AGENTIC_NOTES_INTERNAL),
            "list-notes",
            "--scope",
            "project",
            "--agent-type",
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
    assert "#### Project: research-coordinator" in rendered
    assert "Directory:" in listed.stdout


def test_compaction_refresh_pulls_notes_and_rematerializes_instructions(tmp_path: Path) -> None:
    org_remote = seed_org_remote(tmp_path)
    project_remote = seed_project_remote(tmp_path)
    project = clone_project(tmp_path, project_remote)
    env = base_env(tmp_path, org_remote)

    run([str(AGENTIC_NOTES_INTERNAL), "init-org-notes", "--repo", str(org_remote)], env=env)
    run([str(AGENTIC_NOTES_INTERNAL), "ensure-project-state", "--project-dir", str(project)], env=env)
    state = state_checkout(env)
    (state / "agent-notes" / "all-agents" / "always-injected.md").write_text(
        "# Project Notes\n\nOld project body.\n", encoding="utf-8"
    )
    git(state, "add", "agent-notes/all-agents/always-injected.md")
    git(state, "commit", "-m", "seed old project note")
    git(state, "push")
    run(
        [
            str(AGENTIC_NOTES_INTERNAL),
            "generate-instructions",
            "--project-dir",
            str(project),
            "--agent-type",
            "gpu-kernel-engineer",
            "--cli",
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
            str(AGENTIC_TEAM),
            "--sandbox", "none",
            "--cli",
            "codex",
            *at_launch_args(project, env),
        ],
        env=env,
    )
    assert launch.returncode == 0
    hook = project / ".codex" / "hooks" / "agentic-team-compaction.py"
    assert hook.exists()

    org_update = tmp_path / "org-update"
    run(["git", "clone", str(org_remote), str(org_update)])
    configure_git(org_update)
    (org_update / "agent-notes" / "all-agents" / "always-injected.md").write_text(
        "# Org Notes\n\nFresh org body.\n", encoding="utf-8"
    )
    git(org_update, "add", "agent-notes/all-agents/always-injected.md")
    git(org_update, "commit", "-m", "fresh org note")
    git(org_update, "push")

    state_update = tmp_path / "state-update"
    run(["git", "clone", str(project_remote), str(state_update)])
    configure_git(state_update)
    git(state_update, "fetch", "origin", "agentic/project-state")
    git(state_update, "checkout", "-B", "agentic/project-state", "origin/agentic/project-state")
    (state_update / "agent-notes" / "all-agents" / "always-injected.md").write_text(
        "# Project Notes\n\nFresh project body.\n", encoding="utf-8"
    )
    git(state_update, "add", "agent-notes/all-agents/always-injected.md")
    git(state_update, "commit", "-m", "fresh project note")
    git(state_update, "push", "origin", "agentic/project-state")

    result = run(
        [
            sys.executable,
            str(hook),
            str(project / "AGENTS.md"),
            str(REPO_ROOT / "scripts" / "bin" / "capability-refresh"),
            str(project),
            "research-coordinator",
            "codex",
        ],
        env=env,
        input='{"hook_event_name":"SessionStart"}',
    )

    payload = json.loads(result.stdout)
    text = (project / "AGENTS.md").read_text(encoding="utf-8")
    assert "Agentic Team refreshed post-compaction instructions." in payload["systemMessage"]
    assert "just experienced context compaction" in payload["hookSpecificOutput"]["additionalContext"]
    assert "Fresh org body." in text
    assert "Fresh project body." in text
    assert "Old project body." not in text

    post_compact_result = run(
        [
            sys.executable,
            str(hook),
            "post-compact",
            str(project / "AGENTS.md"),
            str(REPO_ROOT / "scripts" / "bin" / "capability-refresh"),
            str(project),
            "research-coordinator",
            "codex",
        ],
        env=env,
        input='{"hook_event_name":"PostCompact"}',
    )
    post_compact_payload = json.loads(post_compact_result.stdout)
    assert "just experienced context compaction" in post_compact_payload["systemMessage"]
    assert "hookSpecificOutput" not in post_compact_payload
    assert (hook.parent / ".agentic-team-compaction.pending").exists()

    inject_result = run(
        [
            sys.executable,
            str(hook),
            "inject-pending",
            str(project / "AGENTS.md"),
            str(REPO_ROOT / "scripts" / "bin" / "capability-refresh"),
            str(project),
            "research-coordinator",
            "codex",
        ],
        env=env,
        input='{"hook_event_name":"UserPromptSubmit"}',
    )
    inject_payload = json.loads(inject_result.stdout)
    assert inject_payload["suppressOutput"] is True
    assert inject_payload["hookSpecificOutput"]["hookEventName"] == "UserPromptSubmit"
    assert "just experienced context compaction" in inject_payload["hookSpecificOutput"]["additionalContext"]
    assert not (hook.parent / ".agentic-team-compaction.pending").exists()


def test_note_updater_creates_new_org_note_and_commits(tmp_path: Path) -> None:
    org_remote = seed_org_remote(tmp_path)
    project = tmp_path / "project"
    project.mkdir()
    env = base_env(tmp_path, org_remote)
    run([str(AGENTIC_NOTES_INTERNAL), "init-org-notes", "--repo", str(org_remote)], env=env)
    request = make_request(
        tmp_path,
        {
            "kind": "note_update_request",
            "target": {"scope": "org", "agent_type": "all-agents", "note_name": "git"},
            "summary": "Prefer named staging.",
            "lesson": "Stage files by explicit path instead of using git add all.",
            "source": {"user_id": "alice", "agent_type": "gpu-kernel-engineer"},
        },
    )

    run([str(AGENTIC_NOTES_INTERNAL), "update-note", "--request", str(request), "--project-dir", str(project)], env=env)

    checkout = org_checkout(env)
    assert "Stage files by explicit path" in (checkout / "agent-notes" / "all-agents" / "git.md").read_text()
    assert "notes: update agent-notes/all-agents/git.md" in git(checkout, "log", "-1", "--pretty=%s").stdout


def test_note_update_stores_lesson_without_summary_or_rationale_boilerplate(tmp_path: Path) -> None:
    org_remote = seed_org_remote(tmp_path)
    project = tmp_path / "project"
    project.mkdir()
    env = base_env(tmp_path, org_remote)
    run([str(AGENTIC_NOTES_INTERNAL), "init-org-notes", "--repo", str(org_remote)], env=env)
    request = make_request(
        tmp_path,
        {
            "kind": "note_update_request",
            "target": {"scope": "org", "agent_type": "all-agents", "note_name": "gpu-runtime"},
            "summary": "ROCm runtime mismatch",
            "lesson": "Check PyTorch device visibility before launching local ROCm GPU jobs.",
            "rationale": "rocm-smi listed devices but the active uv environment reported zero torch devices on 2026-07-01",
        },
    )

    run([str(AGENTIC_NOTES_INTERNAL), "update-note", "--request", str(request), "--project-dir", str(project)], env=env)

    checkout = org_checkout(env)
    text = (checkout / "agent-notes" / "all-agents" / "gpu-runtime.md").read_text()
    assert "Topic hints: ROCm runtime mismatch" in text
    assert "- Check PyTorch device visibility before launching local ROCm GPU jobs." in text
    assert "ROCm runtime mismatch:" not in text
    assert "rocm-smi listed devices" not in text


def test_rewrite_note_replaces_one_note_through_agent_command(tmp_path: Path) -> None:
    org_remote = seed_org_remote(tmp_path)
    project = tmp_path / "project"
    project.mkdir()
    env = base_env(tmp_path, org_remote)
    run([str(AGENTIC_NOTES_INTERNAL), "init-org-notes", "--repo", str(org_remote)], env=env)
    update_request = make_request(
        tmp_path,
        {
            "kind": "note_update_request",
            "target": {"scope": "org", "agent_type": "all-agents", "note_name": "gpu-runtime"},
            "summary": "PyTorch device visibility",
            "lesson": "Check PyTorch device visibility before launching local GPU jobs.",
        },
    )
    run([str(AGENTIC_NOTES_INTERNAL), "update-note", "--request", str(update_request), "--project-dir", str(project)], env=env)
    rewrite_request = {
        "target": {"scope": "org", "agent_type": "all-agents", "note_name": "gpu-runtime"},
        "content": "# Gpu Runtime\n\n## Lessons\n\n- Check PyTorch device visibility before local ROCm or CUDA jobs.\n",
    }

    result = run(
        [
            str(AGENTIC_NOTES),
            "rewrite-note",
        ],
        input=yaml.safe_dump(rewrite_request, sort_keys=False),
        env=env,
    )

    response = json.loads(result.stdout)
    assert response["command"] == "agentic-notes rewrite-note"
    checkout = org_checkout(env)
    text = (checkout / "agent-notes" / "all-agents" / "gpu-runtime.md").read_text()
    assert "before local ROCm or CUDA jobs" in text
    assert "before launching local GPU jobs" not in text
    assert "notes: replace agent-notes/all-agents/gpu-runtime.md" in git(checkout, "log", "-1", "--pretty=%s").stdout


def test_note_updater_does_not_duplicate_existing_agent_type_bullet(tmp_path: Path) -> None:
    org_remote = seed_org_remote(tmp_path)
    project = tmp_path / "project"
    project.mkdir()
    env = base_env(tmp_path, org_remote)
    run([str(AGENTIC_NOTES_INTERNAL), "init-org-notes", "--repo", str(org_remote)], env=env)
    checkout = org_checkout(env)
    note = checkout / "agent-notes" / "gpu-kernel-engineer" / "triton.md"
    note.write_text("# Triton\n\n## Lessons\n\n- Keep BLOCK power-of-two.\n", encoding="utf-8")
    git(checkout, "add", str(note.relative_to(checkout)))
    git(checkout, "commit", "-m", "seed agent type triton note")
    git(checkout, "push")
    request = make_request(
        tmp_path,
        {
            "kind": "note_update_request",
            "target": {"scope": "org", "agent_type": "gpu-kernel-engineer", "note_name": "triton"},
            "summary": "Power-of-two blocks.",
            "lesson": "Keep BLOCK power-of-two.",
            "source": {"user_id": "alice", "agent_type": "gpu-kernel-engineer"},
        },
    )

    run([str(AGENTIC_NOTES_INTERNAL), "update-note", "--request", str(request), "--project-dir", str(project)], env=env)

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
                "agent_type": "all-agents",
                "note_name": "evaluation",
            },
            "summary": "Use fixed eval split.",
            "lesson": "Keep the evaluation split unchanged across experiments.",
            "source": {"user_id": "alice"},
        },
    )

    run([str(AGENTIC_NOTES_INTERNAL), "update-note", "--request", str(request), "--project-dir", str(project)], env=env)

    inspect = tmp_path / "inspect-state"
    run(["git", "clone", "-b", "agentic/project-state", str(project_remote), str(inspect)])
    assert "evaluation split unchanged" in (
        inspect / "agent-notes" / "all-agents" / "evaluation.md"
    ).read_text()


def test_project_state_initialization_creates_required_layout(tmp_path: Path) -> None:
    project_remote = seed_project_remote(tmp_path)
    project = clone_project(tmp_path, project_remote)
    env = base_env(tmp_path)

    run([str(AGENTIC_NOTES_INTERNAL), "ensure-project-state", "--project-dir", str(project)], env=env)

    state = state_checkout(env)
    always_injected = state / "agent-notes" / "all-agents" / "always-injected.md"
    assert always_injected.exists()
    assert always_injected.read_text(encoding="utf-8") == ""
    assert not (state / "work-state").exists()
    assert not (state / "experiment-log").exists()
    assert not (state / "README.md").exists()
    head_with_parents = git(state, "rev-list", "--parents", "-n", "1", "HEAD").stdout.split()
    assert len(head_with_parents) == 1


def test_work_state_files_render_plan_and_stay_off_code_branch(tmp_path: Path) -> None:
    project_remote = seed_project_remote(tmp_path)
    project = clone_project(tmp_path, project_remote)
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    make_executable(fake_bin / "codex", "#!/bin/sh\nexit 0\n")
    env = base_env(tmp_path)
    env["PATH"] = f"{fake_bin}:{env['PATH']}"
    plan = tmp_path / "plan.md"
    report = tmp_path / "report.md"
    todo = tmp_path / "TODO.md"
    figure = tmp_path / "baseline.png"
    plan.write_text(
        "# Research Plan: kernel-search\n\n"
        "**Goal:** Find a faster sparse attention kernel.\n\n"
        "**Current Next Steps:**\n"
        "- Run the baseline benchmark.\n",
        encoding="utf-8",
    )
    report.write_text(
        "# Research Log\n\nBaseline pending.\n",
        encoding="utf-8",
    )
    todo.write_text("- [ ] Run baseline benchmark\n", encoding="utf-8")
    figure.write_bytes(b"not-a-real-png")

    run(
        [
            str(AGENTIC_NOTES_INTERNAL),
            "replace-note",
            "--project-dir",
            str(project),
            "--scope",
            "work",
            "--work-branch",
            "kernel-search",
            "--agent-type",
            "research-coordinator",
            "--note-name",
            "always-injected",
            "--note-file",
            str(plan),
            "--refresh-parent",
            "--cli",
            "codex",
        ],
        env=env,
    )
    work_state = work_state_dir(env)
    (work_state / "report.md").write_text(report.read_text(encoding="utf-8"), encoding="utf-8")
    (work_state / "TODO.md").write_text(todo.read_text(encoding="utf-8"), encoding="utf-8")
    (work_state / "images").mkdir()
    (work_state / "images" / "baseline.png").write_bytes(figure.read_bytes())
    git(work_state, "add", "report.md", "TODO.md", "images/")
    git(work_state, "commit", "-m", "work-state: update research records")
    git(work_state, "push")

    stored_plan = work_state / "agent-notes" / "research-coordinator" / "always-injected.md"
    assert stored_plan.read_text(encoding="utf-8") == plan.read_text(encoding="utf-8")
    assert (work_state / "report.md").read_text(encoding="utf-8") == report.read_text(encoding="utf-8")
    assert (work_state / "TODO.md").read_text(encoding="utf-8") == todo.read_text(encoding="utf-8")
    assert (work_state / "images" / "baseline.png").read_bytes() == figure.read_bytes()
    assert not (project / "report.md").exists()
    assert not (project / "TODO.md").exists()
    assert not (project / "images" / "baseline.png").exists()

    instruction_text = (project / "AGENTS.md").read_text(encoding="utf-8")
    assert "## Agentic State" in instruction_text
    assert "agentic/work-state/kernel-search" in instruction_text
    assert 'WORK_STATE_DIR="${AR_WORK_STATE_DIR:?}"' in instruction_text
    assert 'mkdir -p "$WORK_STATE_DIR/images"' in instruction_text
    assert 'git -C "$WORK_STATE_DIR" add report.md TODO.md images/' in instruction_text
    assert "$WORK_STATE_DIR/images/" in instruction_text
    assert (
        "do not skip report-ready PNG/PDF figures merely because they are binary files"
        in " ".join(instruction_text.split())
    )
    assert "**Goal:** Find a faster sparse attention kernel." in instruction_text
    assert "#### Work branch: kernel-search / research-coordinator" in instruction_text
    assert "No work-branch always-injected guidance" not in instruction_text
    assert "--name research-plan" not in instruction_text

    rendered_plan = run(
        [
            str(AGENTIC_NOTES),
            "read-note",
            "--project-dir",
            str(project),
            "--agent-type",
            "research-coordinator",
            "always-injected",
        ],
        env=env,
    ).stdout
    assert "## Work branch: kernel-search / research-coordinator" in rendered_plan
    assert "**Goal:** Find a faster sparse attention kernel." in rendered_plan

    legacy_notes_command = "at" "-notes"
    assert not (REPO_ROOT / "capabilities" / "agentic-notes" / "bin" / legacy_notes_command).exists()

    missing_summary = run(
        [
            str(EXPERIMENT_LOG),
            "summary",
            "--project-dir",
            str(project),
            "--work-branch",
            "kernel-search",
        ],
        env=env,
        check=False,
    )
    assert missing_summary.returncode == 1
    assert "experiment summary does not exist" in missing_summary.stderr


def test_named_work_creates_at_layout_and_references_research_context(tmp_path: Path) -> None:
    project_remote = seed_project_remote(tmp_path)
    project = clone_project(tmp_path, project_remote)
    env = base_env(tmp_path)
    env["AR_CAPABILITIES"] = "agentic-notes,experiment-log,research-coordinator"

    plan = tmp_path / "plan.md"
    plan.write_text("# Parent Plan\n\nExplore existing bounds.\n", encoding="utf-8")
    run(
        [
            str(AGENTIC_NOTES_INTERNAL),
            "replace-note",
            "--project-dir",
            str(project),
            "--scope",
            "work",
            "--work-branch",
            "kernel-search",
            "--agent-type",
            "research-coordinator",
            "--note-name",
            "always-injected",
            "--note-file",
            str(plan),
        ],
        env=env,
    )
    parent_state = work_state_dir(env)
    assert_linked_worktree(parent_state)
    (parent_state / "report.md").write_text("# Parent Report\n\nUseful result.\n", encoding="utf-8")
    (parent_state / "TODO.md").write_text("- [ ] Parent todo\n", encoding="utf-8")
    (parent_state / "images").mkdir(exist_ok=True)
    (parent_state / "images" / "parent.png").write_bytes(b"png")
    (parent_state / "context").mkdir(exist_ok=True)
    write_yaml(
        parent_state / "context" / "manifest.yaml",
        {
            "version": 1,
            "references": [
                {
                    "work_name": "ancestor",
                    "work_branch": "agent/ancestor",
                    "state_branch": "agentic/work-state/agent/ancestor",
                    "state_commit": "abc123",
                    "files": ["report.md", "images/ancestor.png"],
                }
            ],
        },
    )
    git(parent_state, "add", "report.md", "TODO.md", "images/", "context/manifest.yaml")
    git(parent_state, "commit", "-m", "work-state: add parent research records")
    git(parent_state, "push")

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    make_executable(fake_bin / "codex", "#!/bin/sh\nexit 0\n")
    env["PATH"] = f"{fake_bin}:{env['PATH']}"

    root = workspace_root(env)
    result = run(
        [
            str(AGENTIC_TEAM),
            "--sandbox",
            "none",
            "--cli",
            "codex",
            str(root),
            "kdtree-bounds",
            "--from",
            "kernel-search",
            "--project-dir",
            str(project),
        ],
        env=env,
    )

    assert result.returncode == 0
    code_dir = root / "kdtree-bounds" / "code"
    state_dir = root / "kdtree-bounds" / "state"
    assert code_dir.exists()
    assert state_dir.exists()
    assert (root / "project").is_symlink()
    assert_linked_worktree(root / "project-state")
    assert_linked_worktree(state_dir)
    assert git(code_dir, "branch", "--show-current").stdout.strip() == "agent/alice/kdtree-bounds"
    report_text = (state_dir / "report.md").read_text(encoding="utf-8")
    assert report_text.startswith("# Research Log: kdtree-bounds")
    assert "Created from `kernel-search` into `agent/alice/kdtree-bounds`" in report_text
    assert (state_dir / "context" / "parent" / "report.md").read_text(encoding="utf-8").startswith("# Parent Report")
    assert (state_dir / "context" / "parent" / "TODO.md").exists()
    assert not (state_dir / "context" / "parent" / "images" / "parent.png").exists()
    manifest = yaml.safe_load((state_dir / "context" / "manifest.yaml").read_text(encoding="utf-8"))
    assert manifest["created_from"]["work_branch"] == "kernel-search"
    assert [entry["work_branch"] for entry in manifest["references"]] == ["agent/ancestor", "kernel-search"]
    assert manifest["references"][0]["files"] == ["report.md", "images/ancestor.png"]
    assert manifest["references"][1]["state_branch"] == "agentic/work-state/kernel-search"
    assert manifest["references"][1]["files"] == ["report.md", "TODO.md", "images/parent.png"]
    readme_text = (state_dir / "context" / "README.md").read_text(encoding="utf-8")
    assert "images/parent.png" in readme_text
    assert (root / "project-state").exists()
    assert (
        git(project, "ls-remote", "--exit-code", "--heads", "origin", "agent/alice/kdtree-bounds", check=False).returncode
        == 2
    )
    assert (
        git(
            project,
            "ls-remote",
            "--exit-code",
            "--heads",
            "origin",
            "agentic/work-state/agent/alice/kdtree-bounds",
            check=False,
        ).returncode
        == 2
    )


def test_named_work_from_agent_branch_uses_sibling_branch_name(tmp_path: Path) -> None:
    project_remote = seed_project_remote(tmp_path)
    project = clone_project(tmp_path, project_remote)
    env = base_env(tmp_path)
    env["AR_CAPABILITIES"] = "none"
    root = workspace_root(env)
    source_code = root / "dan-agent" / "code"
    source_code.parent.mkdir(parents=True)
    root.mkdir(parents=True, exist_ok=True)
    (root / "project").symlink_to(project, target_is_directory=True)
    git(project, "worktree", "add", "-b", "agent/dan-agent", str(source_code), "kernel-search")
    configure_git(source_code)

    result = run(
        [
            str(AGENTIC_WORKSPACE),
            "ensure-work",
            "dan-agent2",
            "--workspace-root",
            str(root),
            "--from",
            "dan-agent",
            "--capabilities",
            "none",
        ],
        env=env,
    )

    assert result.returncode == 0
    code_dir = root / "dan-agent2" / "code"
    assert git(code_dir, "branch", "--show-current").stdout.strip() == "agent/dan-agent2"


def test_named_work_does_not_suffix_when_requested_branch_exists_remotely(tmp_path: Path) -> None:
    project_remote = seed_project_remote(tmp_path)
    project = clone_project(tmp_path, project_remote)
    env = base_env(tmp_path)
    env["AR_CAPABILITIES"] = "none"
    root = workspace_root(env)
    source_code = root / "dan-agent" / "code"
    source_code.parent.mkdir(parents=True)
    root.mkdir(parents=True, exist_ok=True)
    (root / "project").symlink_to(project, target_is_directory=True)
    git(project, "worktree", "add", "-b", "agent/dan-agent", str(source_code), "kernel-search")
    configure_git(source_code)
    git(project, "branch", "agent/dan-agent2", "kernel-search")
    git(project, "push", "origin", "agent/dan-agent2")
    git(project, "branch", "-D", "agent/dan-agent2")

    result = run(
        [
            str(AGENTIC_WORKSPACE),
            "ensure-work",
            "dan-agent2",
            "--workspace-root",
            str(root),
            "--from",
            "dan-agent",
            "--capabilities",
            "none",
        ],
        env=env,
        check=False,
    )

    assert result.returncode == 1
    assert "agent/dan-agent2" in result.stderr
    assert "origin/agent/dan-agent2" in result.stderr
    assert "dan-agent2-2" not in result.stderr
    assert not (root / "dan-agent2" / "code").exists()


def test_project_state_uses_directory_name_when_no_remote_exists(tmp_path: Path) -> None:
    project = tmp_path / "project-without-remote"
    project.mkdir()
    env = base_env(tmp_path)

    result = run(
        [str(AGENTIC_NOTES_INTERNAL), "ensure-project-state", "--project-dir", str(project)],
        env=env,
        check=False,
    )

    assert result.returncode == 0
    assert (tmp_path / "project-without-remote-at" / "project-state").exists()


def test_project_state_uses_checkout_name_even_with_git_remote(tmp_path: Path) -> None:
    project_remote = seed_project_remote(tmp_path)
    project = clone_project(tmp_path, project_remote)
    env = base_env(tmp_path)

    result = run(
        [str(AGENTIC_NOTES_INTERNAL), "ensure-project-state", "--project-dir", str(project)],
        env=env,
        check=False,
    )

    assert result.returncode == 0
    assert_linked_worktree(workspace_root(env, "project") / "project-state")
    assert (
        workspace_root(env, "project")
        / "project-state"
        / "agent-notes"
        / "all-agents"
        / "always-injected.md"
    ).exists()


def test_launcher_branch_guard_blocks_same_branch_but_not_other_branches(tmp_path: Path) -> None:
    project_remote = seed_project_remote(tmp_path)
    project = clone_project(tmp_path, project_remote)
    git(project, "branch", "paper-draft", "kernel-search")
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    make_executable(fake_bin / "codex", "#!/bin/sh\nexit 0\n")
    env = base_env(tmp_path)
    env.pop("AR_WORK_BRANCH", None)
    env["PATH"] = f"{fake_bin}:{env['PATH']}"
    env["AR_CAPABILITIES"] = "none"

    guard_dir = workspace_root(env) / ".runtime" / "branch-guards" / "kernel-search"
    guard_dir.mkdir(parents=True)
    (guard_dir / "session-one.guard").write_text(
        "\n".join(
            [
                "session_id=session-one",
                "main_agent=research-coordinator",
                "pid=12345",
                "host=test-host",
                f"workspace={project}",
                "started_at=2026-06-30T00:00:00Z",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    blocked = run(
        [
            str(AGENTIC_TEAM),
            "--sandbox",
            "none",
            "--cli",
            "codex",
            *at_launch_args(project, env),
        ],
        env=env,
        check=False,
    )
    other = run(
        [
            str(AGENTIC_TEAM),
            "--sandbox",
            "none",
            "--cli",
            "codex",
            *at_launch_args(project, env, "paper-draft", "paper-draft"),
        ],
        env=env,
    )

    assert blocked.returncode == 1
    assert "appears to be using branch 'kernel-search'" in blocked.stdout
    assert "work/alice" in blocked.stdout
    assert other.returncode == 0
    assert "Work branch:   paper-draft" in other.stdout


def test_remote_repo_spec_detects_scp_style_remotes() -> None:
    loader = SourceFileLoader("ar_notes_remote_spec_test", str(AGENTIC_NOTES_INTERNAL))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    assert spec is not None
    at_notes = importlib.util.module_from_spec(spec)
    loader.exec_module(at_notes)

    assert at_notes.is_remote_repo_spec("dan-git@localhost:org-agentic-state.git")
    assert at_notes.is_remote_repo_spec("git@github.com:SmerkyG/abctest.git")
    assert not at_notes.is_remote_repo_spec("/tmp/abctest.git")


def test_init_org_notes_treats_scp_style_repo_as_remote(tmp_path: Path) -> None:
    loader = SourceFileLoader("ar_notes_scp_org_remote_test", str(AGENTIC_NOTES_INTERNAL))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    assert spec is not None
    at_notes = importlib.util.module_from_spec(spec)
    loader.exec_module(at_notes)

    remote = "dan-git@localhost:org-agentic-state.git"
    checkout_calls = []

    def fail_local_repo(repo: Path, branch: str) -> Path:
        raise AssertionError(f"scp-style remote was treated as a local path: {repo}")

    def fake_checkout(repo_url: str | None = None) -> None:
        checkout_calls.append(repo_url)
        return None

    at_notes.ensure_local_git_repo = fail_local_repo
    at_notes.ensure_org_checkout = fake_checkout
    old_cwd = Path.cwd()
    os.chdir(tmp_path)
    try:
        at_notes.init_org_notes(SimpleNamespace(repo=remote))
    finally:
        os.chdir(old_cwd)

    assert checkout_calls == [remote]
    assert not (tmp_path / remote).exists()


def test_init_org_notes_creates_empty_always_injected_placeholder(tmp_path: Path) -> None:
    org_repo = tmp_path / "org-notes"
    env = base_env(tmp_path)

    run([str(AGENTIC_NOTES_INTERNAL), "init-org-notes", "--repo", str(org_repo)], env=env)

    note = org_repo / "agent-notes" / "all-agents" / "always-injected.md"
    assert note.exists()
    assert note.read_text(encoding="utf-8") == ""


def test_update_note_refresh_parent_locks_org_and_parent_project(tmp_path: Path) -> None:
    request = make_request(
        tmp_path,
        {
            "kind": "note_update_request",
            "target": {"scope": "org", "agent_type": "all-agents", "note_name": "git"},
            "summary": "Lock test.",
            "lesson": "Lock test.",
        },
    )
    previous = {
        "AR_STATE_ROOT": os.environ.get("AR_STATE_ROOT"),
        "AR_ORG_NOTES_REPO": os.environ.get("AR_ORG_NOTES_REPO"),
    }
    os.environ["AR_STATE_ROOT"] = str(tmp_path / "state")
    os.environ["AR_ORG_NOTES_REPO"] = str(tmp_path / "org.git")
    try:
        loader = SourceFileLoader("ar_notes_lock_test", str(AGENTIC_NOTES_INTERNAL))
        spec = importlib.util.spec_from_loader(loader.name, loader)
        assert spec is not None
        at_notes = importlib.util.module_from_spec(spec)
        loader.exec_module(at_notes)
        locks = at_notes.lock_paths_for_args(
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
    assert "project.lock" in lock_names


def experiment_request(tmp_path: Path, short_description: str, key_result: str = "passed") -> Path:
    return make_request(
        tmp_path,
        {
            "kind": "experiment_result_request",
            "user_id": "alice",
            "short_description": short_description,
            "title": short_description,
            "description": "Test experiment.",
            "source": {"actor_id": "gpu-kernel-engineer", "agent_type": "gpu-kernel-engineer"},
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
            str(EXPERIMENT_LOG),
            "append",
            "--request",
            str(experiment_request(tmp_path, "Triton power-of-two shape test")),
            "--project-dir",
            str(project),
        ],
        env=env,
    ).stdout.strip()
    second = run(
        [
            str(EXPERIMENT_LOG),
            "append",
            "--request",
            str(experiment_request(tmp_path, "Attention odd seq benchmark")),
            "--project-dir",
            str(project),
        ],
        env=env,
    ).stdout.strip()

    log_dir = work_log(env)
    first_id = local_experiment_id(first)
    second_id = local_experiment_id(second)
    assert first == "kernel-search::E0001_triton-power-of-two-shape-test"
    assert second == "kernel-search::E0002_attention-odd-seq-benchmark"
    assert (log_dir / "experiments" / f"{first_id}.yaml").exists()
    assert (log_dir / "experiments" / f"{second_id}.yaml").exists()
    counter = yaml.safe_load((log_dir / "COUNTER.yaml").read_text())
    assert counter["next_experiment_number"] == 3
    assert "next_correction_number" not in counter
    summary = (log_dir / "SUMMARY.md").read_text()
    assert len(summary_rows(summary)) == 2
    assert first_id in summary
    assert second_id in summary


def test_successful_experiment_creates_local_success_tag(tmp_path: Path) -> None:
    project_remote = seed_project_remote(tmp_path)
    project = clone_project(tmp_path, project_remote)
    env = base_env(tmp_path)
    commit = git(project, "rev-parse", "HEAD").stdout.strip()
    request = make_request(
        tmp_path,
        {
            "kind": "experiment_result_request",
            "user_id": "alice",
            "short_description": "Successful run",
            "title": "Successful run",
            "description": "Test experiment.",
            "source": {"actor_id": "research-coordinator", "agent_type": "research-coordinator"},
            "code": {"repo": "local", "branch": "kernel-search", "commit": commit, "dirty": False},
            "command": "uv run pytest",
            "status": "completed",
            "success": True,
            "key_result": "new best result",
            "metrics": {"tests_passed": 1},
            "artifacts": {},
            "notes": "",
        },
    )

    experiment_ref = run(
        [
            str(EXPERIMENT_LOG),
            "append",
            "--request",
            str(request),
            "--project-dir",
            str(project),
        ],
        env=env,
    ).stdout.strip()

    experiment_id = local_experiment_id(experiment_ref)
    tag_name = f"exp/kernel-search/{experiment_id}-success"
    assert git(project, "rev-list", "-n", "1", tag_name).stdout.strip() == commit
    experiment_doc = yaml.safe_load((work_log(env) / "experiments" / f"{experiment_id}.yaml").read_text())
    assert experiment_doc["success"] is True


def test_summary_is_append_only_and_existing_experiment_files_are_unchanged(tmp_path: Path) -> None:
    project_remote = seed_project_remote(tmp_path)
    project = clone_project(tmp_path, project_remote)
    env = base_env(tmp_path)
    first = run(
        [
            str(EXPERIMENT_LOG),
            "append",
            "--request",
            str(experiment_request(tmp_path, "First run")),
            "--project-dir",
            str(project),
        ],
        env=env,
    ).stdout.strip()
    log_dir = work_log(env)
    first_id = local_experiment_id(first)
    first_file = log_dir / "experiments" / f"{first_id}.yaml"
    first_content = first_file.read_text(encoding="utf-8")
    hidden = log_dir / "experiments" / "E9999_hidden.yaml"
    hidden.write_text("kind: experiment_result\nexperiment_id: E9999_hidden\n", encoding="utf-8")
    state = work_state_checkout(env)
    git(state, "add", str(hidden.relative_to(state)))
    git(state, "commit", "-m", "add hidden experiment")
    git(state, "push")

    second = run(
        [
            str(EXPERIMENT_LOG),
            "append",
            "--request",
            str(experiment_request(tmp_path, "Second run")),
            "--project-dir",
            str(project),
        ],
        env=env,
    ).stdout.strip()

    summary = (log_dir / "SUMMARY.md").read_text()
    assert first_file.read_text(encoding="utf-8") == first_content
    assert local_experiment_id(second) in summary
    assert "E9999_hidden" not in summary


def test_push_conflict_retries_with_next_counter_number(tmp_path: Path) -> None:
    project_remote = seed_project_remote(tmp_path)
    project_one = clone_project(tmp_path, project_remote, "project-one")
    project_two = clone_project(tmp_path, project_remote, "project-two")
    env_one = base_env(tmp_path / "one")
    env_two = base_env(tmp_path / "two")
    env_one["AR_WORKSPACE_ROOT"] = str(tmp_path / "one" / "conflict-project-at")
    env_two["AR_WORKSPACE_ROOT"] = str(tmp_path / "two" / "conflict-project-at")

    run([str(EXPERIMENT_LOG), "summary", "--project-dir", str(project_one), "--work-branch", "kernel-search"], env=env_one, check=False)
    run([str(EXPERIMENT_LOG), "summary", "--project-dir", str(project_two), "--work-branch", "kernel-search"], env=env_two, check=False)
    state_two = work_state_checkout(env_two)
    waiting = tmp_path / "waiting"
    allow = tmp_path / "allow"
    write_pre_push_hook(
        state_two,
        "#!/bin/sh\n"
        f"touch '{waiting}'\n"
        f"while [ ! -f '{allow}' ]; do sleep 0.05; done\n",
    )

    proc_two = subprocess.Popen(
        [
            str(EXPERIMENT_LOG),
            "append",
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
            str(EXPERIMENT_LOG),
            "append",
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
    assert winner.startswith("kernel-search::E0001_")
    assert loser.startswith("kernel-search::E0002_")


def test_same_installation_multiple_actor_worktrees_serialize_project_log_updates(tmp_path: Path) -> None:
    project_remote = seed_project_remote(tmp_path)
    project_one = clone_project(tmp_path, project_remote, "actor-one")
    project_two = clone_project(tmp_path, project_remote, "actor-two")
    env = base_env(tmp_path)
    env["AR_WORKSPACE_ROOT"] = str(tmp_path / "shared-worktree-project-at")

    run([str(EXPERIMENT_LOG), "summary", "--project-dir", str(project_one), "--work-branch", "kernel-search"], env=env, check=False)
    state = work_state_checkout(env)
    waiting = tmp_path / "same-install-waiting"
    allow = tmp_path / "same-install-allow"
    write_pre_push_hook(
        state,
        "#!/bin/sh\n"
        f"touch '{waiting}'\n"
        f"while [ ! -f '{allow}' ]; do sleep 0.05; done\n",
    )

    proc_one = subprocess.Popen(
        [
            str(EXPERIMENT_LOG),
            "append",
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
            str(EXPERIMENT_LOG),
            "append",
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
    assert stdout_one.strip().startswith("kernel-search::E0001_")
    assert stdout_two.strip().startswith("kernel-search::E0002_")
    summary = (work_log(env) / "SUMMARY.md").read_text()
    assert len(summary_rows(summary)) == 2


def test_correction_logging_appends_to_experiment_file_and_summary_row(tmp_path: Path) -> None:
    project_remote = seed_project_remote(tmp_path)
    project = clone_project(tmp_path, project_remote)
    env = base_env(tmp_path)
    experiment_id = run(
        [
            str(EXPERIMENT_LOG),
            "append",
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
            str(EXPERIMENT_LOG),
            "correct",
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
            str(EXPERIMENT_LOG),
            "correct",
            "--request",
            str(second_request),
            "--project-dir",
            str(project),
        ],
        env=env,
    ).stdout.strip()

    log_dir = work_log(env)
    local_id = local_experiment_id(experiment_id)
    experiment_path = log_dir / "experiments" / f"{local_id}.yaml"
    experiment_doc = yaml.safe_load(experiment_path.read_text())
    assert correction_id == "kernel-search::E0001_R001"
    assert second_correction_id == "kernel-search::E0001_R002"
    assert [entry["correction_id"] for entry in experiment_doc["corrections"]] == [
        "E0001_R001",
        "E0001_R002",
    ]
    assert experiment_doc["corrections"][0]["correction"] == "Use the fixed validation split."
    assert not (log_dir / "corrections").exists()
    summary = (log_dir / "SUMMARY.md").read_text()
    assert "E0001_R001" in summary
    assert "E0001_R002" in summary
    assert f"experiments/{local_id}.yaml" in summary


def make_executable(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def test_launcher_uses_unoccupied_agent_branch(tmp_path: Path) -> None:
    project_remote = seed_project_remote(tmp_path)
    project = clone_project(tmp_path, project_remote)
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    make_executable(fake_bin / "codex", "#!/bin/sh\nexit 0\n")
    env = base_env(tmp_path)
    env.pop("AR_WORK_BRANCH", None)
    env["PATH"] = f"{fake_bin}:{env['PATH']}"

    result = run(
        [
            str(AGENTIC_TEAM),
            "--sandbox",
            "none",
            "--cli",
            "codex",
            *at_launch_args(project, env),
        ],
        env=env,
    )

    assert result.returncode == 0, result.stderr
    assert "Work branch:   kernel-search" in result.stdout
    assert "Ownership:      exclusive" in result.stdout
    instruction_text = (project / "AGENTS.md").read_text(encoding="utf-8")
    assert "## Agent Branch" not in instruction_text
    assert "Active branch: `kernel-search`." not in instruction_text
    assert "Branch ownership mode: `exclusive`." not in instruction_text
    assert "No conflicting local branch guard was detected at launch." not in instruction_text
    assert "The user explicitly accepted the launcher branch warning" not in instruction_text
    assert "kernel-search/exp/<experiment-name>" not in instruction_text


def test_launcher_render_only_rewrites_managed_instruction_and_normalizes_whitespace(tmp_path: Path) -> None:
    project_remote = seed_project_remote(tmp_path)
    project = clone_project(tmp_path, project_remote)
    env = base_env(tmp_path)
    (project / "AGENTS.md").write_text(
        "# Research Agent Instructions\n\n"
        "stale generated base\n"
        "\n\n\n\n\n"
        "<!-- AGENTIC-TEAM-MAIN-AGENT-START name=research-coordinator -->\n"
        "old generated main agent\n"
        "<!-- AGENTIC-TEAM-MAIN-AGENT-END -->\n",
        encoding="utf-8",
    )

    result = run(
        [
            str(AGENTIC_TEAM),
            "--sandbox",
            "none",
            "--cli",
            "codex",
            "--render-only",
            str(project),
        ],
        env=env,
    )

    assert result.returncode == 0
    assert f"Rendered instruction file: {project / 'AGENTS.md'}" in result.stdout
    text = (project / "AGENTS.md").read_text(encoding="utf-8")
    assert text.startswith("# Global Instructions")
    assert "# Research Agent Instructions" not in text.splitlines()[0]
    assert "stale generated base" not in text
    assert "old generated main agent" not in text
    assert "\n\n\n\n" not in text
    assert "## Agentic Notes" in text
    assert "## Agent Branch" not in text
    assert "<!-- AGENTIC-TEAM-MAIN-AGENT-START" not in text
    assert "<!-- AGENTIC-TEAM-MODULE-START" not in text
    assert "<!-- AGENTIC-TEAM-PROVIDER-START" not in text
    assert "<!-- AGENTIC-TEAM-NOTES-START" not in text
    assert "<!-- AGENTIC-TEAM-TOPIC-START" not in text
    assert "<!-- AGENTIC-TEAM-SUBAGENTS-START" not in text
    assert text.count("<!--") == 0
    assert (project / ".codex" / "agents" / "experiment-logger.toml").exists()


def test_launcher_passive_startup_does_not_push_agentic_state_branches(tmp_path: Path) -> None:
    project_remote = seed_project_remote(tmp_path)
    project = clone_project(tmp_path, project_remote)
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    make_executable(fake_bin / "codex", "#!/bin/sh\nexit 0\n")
    env = base_env(tmp_path)
    env["PATH"] = f"{fake_bin}:{env['PATH']}"

    result = run(
        [
            str(AGENTIC_TEAM),
            "--sandbox",
            "none",
            "--cli",
            "codex",
            "--render-only",
            str(project),
        ],
        env=env,
    )

    assert result.returncode == 0, result.stderr
    remote_refs = run(
        ["git", "ls-remote", "--heads", str(project_remote), "agentic/*"]
    ).stdout
    assert remote_refs == ""

    result = run(
        [
            str(AGENTIC_TEAM),
            "--sandbox",
            "none",
            "--cli",
            "codex",
            *at_launch_args(project, env),
        ],
        env=env,
    )

    assert result.returncode == 0, result.stderr
    remote_refs = run(
        ["git", "ls-remote", "--heads", str(project_remote), "agentic/*"]
    ).stdout
    assert remote_refs == ""


def test_main_agent_required_capabilities_are_added_to_empty_selection(tmp_path: Path) -> None:
    project_remote = seed_project_remote(tmp_path)
    project = clone_project(tmp_path, project_remote)
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    make_executable(fake_bin / "codex", "#!/bin/sh\nexit 0\n")
    env = base_env(tmp_path)
    env["PATH"] = f"{fake_bin}:{env['PATH']}"
    env["AR_CAPABILITIES"] = "none"

    result = run(
        [
            str(AGENTIC_TEAM),
            "--sandbox",
            "none",
            "--cli",
            "codex",
            "--render-only",
            str(project),
        ],
        env=env,
    )

    assert result.returncode == 0, result.stderr
    text = (project / "AGENTS.md").read_text(encoding="utf-8")
    assert "## Agentic Notes" in text
    assert "## Agentic State" in text
    assert "## Experiment Log" in text
    assert (project / ".codex" / "agents" / "experiment-logger.toml").exists()


def test_systems_developer_required_capabilities_do_not_add_experiment_log(tmp_path: Path) -> None:
    project_remote = seed_project_remote(tmp_path)
    project = clone_project(tmp_path, project_remote)
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    make_executable(fake_bin / "codex", "#!/bin/sh\nexit 0\n")
    env = base_env(tmp_path)
    env["PATH"] = f"{fake_bin}:{env['PATH']}"
    env["AR_CAPABILITIES"] = "none"

    result = run(
        [
            str(AGENTIC_TEAM),
            "--sandbox",
            "none",
            "--cli",
            "codex",
            "--render-only",
            "--main-agent",
            "systems-developer",
            str(project),
        ],
        env=env,
    )

    assert result.returncode == 0, result.stderr
    text = (project / "AGENTS.md").read_text(encoding="utf-8")
    assert "## Agentic Notes" in text
    assert "## Experiment Log" not in text


def test_launcher_refuses_main_branch_without_permission_in_noninteractive_mode(tmp_path: Path) -> None:
    project_remote = seed_project_remote(tmp_path)
    project = clone_project(tmp_path, project_remote)
    git(project, "switch", "main")
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    make_executable(fake_bin / "codex", "#!/bin/sh\nexit 0\n")
    env = base_env(tmp_path)
    env.pop("AR_WORK_BRANCH", None)
    env["PATH"] = f"{fake_bin}:{env['PATH']}"
    env["AR_CAPABILITIES"] = "none"

    result = run(
        [
            str(AGENTIC_TEAM),
            "--sandbox",
            "none",
            "--cli",
            "codex",
            str(project),
        ],
        env=env,
        check=False,
    )

    assert result.returncode == 1
    assert "must launch from an AT work entry" in result.stdout
    assert "Current branch: main" in result.stdout
    assert "agentic-team" in result.stdout
    assert "--project-dir" in result.stdout


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
        "<!-- Generated by agentic-team. Edit the source skill to change this file. -->\n",
        encoding="utf-8",
    )

    result = run(
        [
            str(AGENTIC_TEAM),
            "--sandbox", "none",
            "--cli",
            "codex",
            "--render-only",
            str(project),
        ],
        env=env,
    )

    assert result.returncode == 0
    assert (project / ".agents" / "skills" / "do_research" / "SKILL.md").exists()
    assert not (project / ".agents" / "skills" / "note_usage" / "SKILL.md").exists()
    assert not (project / ".agents" / "skills" / "experiment_log" / "SKILL.md").exists()
    assert (project / ".codex" / "agents" / "note-updater.toml").exists()
    assert (project / ".codex" / "agents" / "experiment-logger.toml").exists()
    assert (project / ".codex" / "agents" / "experiment-corrector.toml").exists()
    assert not (project / ".codex" / "agents" / "branch-committer.toml").exists()
    assert not (project / ".codex" / "agents" / "branch-commit-status.toml").exists()
    assert (project / ".codex" / "agents" / "branch-integrator.toml").exists()
    assert not (project / ".codex" / "agents" / "research-coordinator.toml").exists()
    instruction_text = (project / "AGENTS.md").read_text(encoding="utf-8")
    assert "<!-- AGENTIC-TEAM-MAIN-AGENT-START" not in instruction_text
    assert "<!-- AGENTIC-TEAM-SUBAGENTS-START" not in instruction_text
    assert "## Available Subagents" in instruction_text
    assert "Standing user request" in instruction_text
    assert "If the subagent spawn fails, try to spawn it one more time" in instruction_text
    assert "- `experiment-logger`:" in instruction_text
    assert "- `experiment-corrector`:" in instruction_text
    assert "- `branch-committer`:" not in instruction_text
    assert "- `branch-commit-status`:" not in instruction_text
    assert "- `branch-integrator`:" in instruction_text
    assert "Request: `" not in instruction_text
    assert "Contract: `" in instruction_text
    assert "# Research Coordinator Instructions" in instruction_text
    assert "## Agentic Notes" in instruction_text
    assert "## Agent Branch" not in instruction_text
    assert "<!-- AGENTIC-TEAM-PROVIDER-START" not in instruction_text
    assert instruction_text.count("<!--") == 0
    assert "Org body." in instruction_text


def test_launcher_renders_builtin_systems_developer_main_agent(tmp_path: Path) -> None:
    project_remote = seed_project_remote(tmp_path)
    project = clone_project(tmp_path, project_remote)
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    make_executable(fake_bin / "codex", "#!/bin/sh\nexit 0\n")
    env = base_env(tmp_path)
    env["PATH"] = f"{fake_bin}:{env['PATH']}"

    result = run(
        [
            str(AGENTIC_TEAM),
            "--sandbox",
            "none",
            "--cli",
            "codex",
            "--render-only",
            "--main-agent",
            "systems-developer",
            str(project),
        ],
        env=env,
    )

    assert result.returncode == 0
    assert not (project / ".codex" / "agents" / "systems-developer.toml").exists()
    instruction_text = (project / "AGENTS.md").read_text(encoding="utf-8")
    assert "<!-- AGENTIC-TEAM-MAIN-AGENT-START" not in instruction_text
    assert "# Systems Developer Instructions" in instruction_text
    assert "This is not a research experiment workflow." in instruction_text


def test_launcher_renders_org_agents_and_overrides_builtin_agents(tmp_path: Path) -> None:
    org_remote = init_bare_remote(
        tmp_path,
        "org-agent-extensions",
        {
            "agent-notes/all-agents/always-injected.md": "# Org Notes\n\nOrg body.\n",
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
            "agent-notes/data-curator/always-injected.md": (
                "# Data Curator Agent Type\n\nUse the org dataset checklist.\n"
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
            str(AGENTIC_TEAM),
            "--sandbox",
            "none",
            "--cli",
            "codex",
            "--render-only",
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
            "agent-notes/research-coordinator/always-injected.md": (
                "# Coordinator Agent Type Notes\n\nUse the org coordinator note.\n"
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
            str(AGENTIC_TEAM),
            "--sandbox",
            "none",
            "--cli",
            "codex",
            "--render-only",
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


def test_multiple_main_agents_use_separate_worktrees_and_project_agent_notes(tmp_path: Path) -> None:
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
                "Write from verified experiment logs and project agent-type notes.\n"
            ),
        },
    )
    project_remote = seed_project_remote(tmp_path)
    coordinator = clone_project(tmp_path, project_remote, name="project-coordinator")
    paper = tmp_path / "project-paper"
    run(["git", "-C", str(coordinator), "worktree", "add", "-b", "paper-draft", str(paper), "HEAD"])
    configure_git(paper)

    env = base_env(tmp_path, org_remote)
    env["AR_WORKSPACE_ROOT"] = str(tmp_path / "project-at")
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
    for agent_type, note in (
        ("research-coordinator", coordinator_note),
        ("research-paper-author", paper_note),
    ):
        run(
            [
                str(AGENTIC_NOTES_INTERNAL),
                "replace-note",
                "--project-dir",
                str(coordinator),
                "--scope",
                "project",
                "--agent-type",
                agent_type,
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
            str(AGENTIC_TEAM),
            "--sandbox",
            "none",
            "--cli",
            "codex",
            "--render-only",
            "--main-agent",
            "research-coordinator",
            str(coordinator),
        ],
        env=env,
    )
    paper_launch = run(
        [
            str(AGENTIC_TEAM),
            "--sandbox",
            "none",
            "--cli",
            "codex",
            "--render-only",
            "--main-agent",
            "research-paper-author",
            "--work-branch",
            "paper-draft",
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
    assert (state / "agent-notes" / "research-coordinator" / "always-injected.md").exists()
    assert (state / "agent-notes" / "research-paper-author" / "always-injected.md").exists()
    assert not (state / "AGENTS.md").exists()
