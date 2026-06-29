import json
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
AGENTIC_RESEARCHER = REPO_ROOT / "agentic-researcher"
BUILD_SCRIPT = REPO_ROOT / "container" / "build.sh"
INSTALL_SCRIPT = REPO_ROOT / "scripts" / "install.sh"
FIRST_SETUP_SCRIPT = REPO_ROOT / "scripts" / "first-setup.sh"
CLEANUP_SCRIPT = REPO_ROOT / "scripts" / "cleanup.sh"
CLI_ADAPTER_DIR = REPO_ROOT / "scripts" / "lib" / "cli"


def make_executable(path: Path, content: str) -> None:
    path.write_text(content)
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


@pytest.fixture
def fake_bin(tmp_path: Path) -> Path:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()

    make_executable(
        bin_dir / "podman",
        "#!/bin/sh\n"
        "printf 'env:https_proxy=%s http_proxy=%s\\n' \"${https_proxy-}\" \"${http_proxy-}\" >> \"${FAKE_PODMAN_LOG:?}\"\n"
        "printf 'cmd:%s %s\\n' \"$0\" \"$*\" >> \"${FAKE_PODMAN_LOG:?}\"\n",
    )
    make_executable(
        bin_dir / "docker",
        "#!/bin/sh\n"
        "printf 'cmd:%s %s\\n' \"$0\" \"$*\" >> \"${FAKE_DOCKER_LOG:?}\"\n",
    )

    real_git = shutil.which("git")
    if real_git is None:
        raise RuntimeError("git is required for tests")
    make_executable(
        bin_dir / "git",
        "#!/bin/sh\n"
        "for arg in \"$@\"; do\n"
        "  if [ \"$arg\" = rev-parse ]; then\n"
        "    printf 'deadbeef\\n'\n"
        "    exit 0\n"
        "  fi\n"
        "done\n"
        f"exec {shlex_quote(real_git)} \"$@\"\n",
    )
    return bin_dir


@pytest.fixture
def base_env(fake_bin: Path, tmp_path: Path) -> dict[str, str]:
    env = os.environ.copy()
    filtered_path = [
        d for d in env["PATH"].split(":")
        if not (Path(d) / "docker").exists()
    ]
    env["PATH"] = f"{fake_bin}:{':'.join(filtered_path)}"
    env["FAKE_PODMAN_LOG"] = str(tmp_path / "podman.log")
    env["FAKE_DOCKER_LOG"] = str(tmp_path / "docker.log")
    env["HOME"] = str(tmp_path / "home")
    env["AR_PROJECT_ID"] = "test-project"
    Path(env["HOME"]).mkdir(parents=True, exist_ok=True)
    return env


def shlex_quote(text: str) -> str:
    return "'" + text.replace("'", "'\"'\"'") + "'"


def run(command: list[str], env: dict[str, str], **kwargs) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        **kwargs,
    )


def read_log(path: str) -> str:
    log_path = Path(path)
    if not log_path.exists():
        return ""
    return log_path.read_text()


def write_xdg_config(xdg_config_home: Path, content: str) -> Path:
    config_dir = xdg_config_home / "agentic-researcher"
    config_dir.mkdir(parents=True, exist_ok=True)
    config_path = config_dir / "config.sh"
    config_path.write_text(content)
    return config_path


def test_build_script_uses_podman_for_podman_runtime(base_env: dict[str, str]) -> None:
    result = run([str(BUILD_SCRIPT), "--runtime", "podman"], base_env)

    assert result.returncode == 0
    assert "Building Podman container" in result.stdout
    assert "Podman image built" in result.stdout
    podman_log = read_log(base_env["FAKE_PODMAN_LOG"])
    assert "cmd:" in podman_log
    assert "build --format docker -t agentic-researcher:latest" in podman_log
    assert read_log(base_env["FAKE_DOCKER_LOG"]) == ""


def test_build_script_reads_xdg_config_for_proxy(base_env: dict[str, str], tmp_path: Path) -> None:
    xdg_config_home = tmp_path / "xdg-config"
    write_xdg_config(
        xdg_config_home,
        'AR_HTTPS_PROXY="http://proxy.example:3128"\nAR_HTTP_PROXY="http://proxy.example:3128"\n',
    )

    result = run(
        [str(BUILD_SCRIPT), "--runtime", "podman"],
        {**base_env, "XDG_CONFIG_HOME": str(xdg_config_home)},
    )

    assert result.returncode == 0
    podman_log = read_log(base_env["FAKE_PODMAN_LOG"])
    assert "env:https_proxy=http://proxy.example:3128 http_proxy=http://proxy.example:3128" in podman_log


def test_launcher_apply_defaults_keeps_real_auth_defaults(base_env: dict[str, str]) -> None:
    result = run(
        [str(AGENTIC_RESEARCHER), "--help"],
        {**base_env, "AR_CLI_TOOL": "claude"},
    )

    assert result.returncode == 0
    claude_adapter = (CLI_ADAPTER_DIR / "claude.sh").read_text()
    opencode_adapter = (CLI_ADAPTER_DIR / "opencode.sh").read_text()
    assert 'AR_AUTH_MODE="${AR_AUTH_MODE:-oauth}"' in claude_adapter
    assert 'AR_API_KEY_ENV="${AR_API_KEY_ENV:-ANTHROPIC_API_KEY}"' in claude_adapter
    assert 'AR_AUTH_MODE="${AR_AUTH_MODE:-tool}"' in opencode_adapter


def test_setup_opencode_reads_api_key_from_configured_env_var(base_env: dict[str, str], tmp_path: Path) -> None:
    opencode_adapter = (CLI_ADAPTER_DIR / "opencode.sh").read_text()
    assert 'local api_key_var="${AR_API_KEY_ENV:-OPENAI_API_KEY}"' in opencode_adapter
    assert 'local api_key="${!api_key_var:-}"' in opencode_adapter


def test_claude_adapter_handles_apptainer_key_forwarding(base_env: dict[str, str]) -> None:
    launcher_text = AGENTIC_RESEARCHER.read_text()
    claude_adapter = (CLI_ADAPTER_DIR / "claude.sh").read_text()
    assert "append_env_arg_from_host_as" in launcher_text
    assert 'append_env_arg_from_host_as "ANTHROPIC_API_KEY" "${AR_API_KEY_ENV:-ANTHROPIC_API_KEY}"' in claude_adapter


def test_claude_workspace_guard_lives_in_claude_adapter() -> None:
    launcher_text = AGENTIC_RESEARCHER.read_text()
    claude_adapter = (CLI_ADAPTER_DIR / "claude.sh").read_text()

    assert "Cannot sandbox Claude config directories" not in launcher_text
    assert "Cannot sandbox Claude config directories" in claude_adapter


def test_claude_rejects_own_config_as_workspace(base_env: dict[str, str]) -> None:
    workspace = Path(base_env["HOME"]) / ".claude"
    workspace.mkdir()

    result = run(
        [str(AGENTIC_RESEARCHER), "--sandbox", "none", "--tool", "claude", str(workspace)],
        base_env,
    )

    assert result.returncode != 0
    assert "Cannot sandbox Claude config directories" in result.stdout + result.stderr


def test_non_claude_cli_does_not_inherit_claude_workspace_guard(base_env: dict[str, str]) -> None:
    fake_bin = Path(base_env["PATH"].split(":", maxsplit=1)[0])
    make_executable(fake_bin / "codex", "#!/bin/sh\nexit 0\n")
    workspace = Path(base_env["HOME"]) / ".claude"
    workspace.mkdir()

    result = run(
        [str(AGENTIC_RESEARCHER), "--sandbox", "none", "--tool", "codex", str(workspace)],
        base_env,
    )

    assert "Cannot sandbox Claude config directories" not in result.stdout + result.stderr
    assert result.returncode == 0


def test_install_help_mentions_xdg_config_path(base_env: dict[str, str]) -> None:
    result = run([str(INSTALL_SCRIPT), "--help"], base_env)

    assert result.returncode == 0
    assert "${XDG_CONFIG_HOME:-$HOME/.config}/agentic-researcher/config.sh" in result.stdout


def test_setup_writes_config_to_xdg_config_home(base_env: dict[str, str], tmp_path: Path) -> None:
    xdg_config_home = tmp_path / "xdg-config"
    result = run(
        [str(FIRST_SETUP_SCRIPT)],
        {**base_env, "XDG_CONFIG_HOME": str(xdg_config_home)},
        input="1\n1\n\n\n\n\n\n\n\n",
    )

    assert result.returncode == 0
    config_path = xdg_config_home / "agentic-researcher" / "config.sh"
    assert config_path.exists()
    config_text = config_path.read_text()
    assert 'AR_ORG_NOTES_REPO=""' in config_text
    assert 'AR_MAIN_AGENT="research-coordinator"' in config_text
    assert not (Path(base_env["HOME"]) / ".config" / "agentic-researcher" / "config.sh").exists()


def test_cleanup_uses_xdg_config_path(base_env: dict[str, str], tmp_path: Path) -> None:
    xdg_config_home = tmp_path / "xdg-config"
    state_root = tmp_path / "state-root"
    state_root.mkdir()
    config_path = write_xdg_config(
        xdg_config_home,
        f'AR_STATE_ROOT="{state_root}"\n',
    )

    result = run(
        [str(CLEANUP_SCRIPT), "--include-config", "--yes"],
        {**base_env, "XDG_CONFIG_HOME": str(xdg_config_home)},
    )

    assert result.returncode == 0
    assert not config_path.exists()
    assert not state_root.exists()


def test_install_script_accepts_podman_runtime(base_env: dict[str, str], tmp_path: Path) -> None:
    install_dir = tmp_path / "install"
    bin_dir = tmp_path / "launcher-bin"
    config_dir = tmp_path / "config"

    result = run(
        [
            str(INSTALL_SCRIPT),
            "--install-dir",
            str(install_dir),
            "--bin-dir",
            str(bin_dir),
            "--sandbox",
            "podman",
            "--write-config",
            "--force",
        ],
        {**base_env, "XDG_CONFIG_HOME": str(config_dir)},
    )

    assert result.returncode == 0
    assert (bin_dir / "agentic-researcher").is_symlink()
    config_text = (config_dir / "agentic-researcher" / "config.sh").read_text()
    assert 'AR_SANDBOX="podman"' in config_text
    assert 'AR_AUTO_BUILD="true"' in config_text
    assert read_log(base_env["FAKE_PODMAN_LOG"]) == ""
    assert read_log(base_env["FAKE_DOCKER_LOG"]) == ""


def test_build_command_builds_with_podman_runtime(base_env: dict[str, str]) -> None:
    result = run([str(BUILD_SCRIPT), "--runtime", "podman"], base_env)

    assert result.returncode == 0
    assert "Building Podman container" in result.stdout
    assert "build --format docker -t agentic-researcher:latest" in read_log(base_env["FAKE_PODMAN_LOG"])
    assert read_log(base_env["FAKE_DOCKER_LOG"]) == ""


def test_build_command_auto_detects_podman_when_docker_is_absent(
    base_env: dict[str, str], fake_bin: Path
) -> None:
    (fake_bin / "docker").unlink()

    result = run([str(BUILD_SCRIPT)], base_env)

    assert result.returncode == 0
    assert "Docker not found, falling back to Podman." in result.stdout
    assert "Building Podman container" in result.stdout
    assert "build --format docker -t agentic-researcher:latest" in read_log(base_env["FAKE_PODMAN_LOG"])
    assert read_log(base_env["FAKE_DOCKER_LOG"]) == ""


def test_launcher_podman_test_mode_overrides_entrypoint(base_env: dict[str, str]) -> None:
    result = run([str(AGENTIC_RESEARCHER), "--sandbox", "podman", "--tool", "codex", "--test"], base_env)

    assert result.returncode == 0
    podman_log = read_log(base_env["FAKE_PODMAN_LOG"])
    assert "run --rm" in podman_log
    assert "-it" not in podman_log
    assert "--userns keep-id" in podman_log
    assert ":/agent-home" in podman_log
    assert f"{REPO_ROOT}:/opt/agentic-researcher:ro" in podman_log
    assert "AR_SANDBOX=podman" in podman_log
    assert "AR_INSTALL_DIR=/opt/agentic-researcher" in podman_log
    assert "AR_NOTES_CLI=/opt/agentic-researcher/scripts/ar-notes" in podman_log
    assert "--entrypoint /bin/bash" in podman_log
    assert "/test_sandbox.sh" in podman_log


def test_launcher_auto_builds_missing_podman_image(
    base_env: dict[str, str], fake_bin: Path, tmp_path: Path
) -> None:
    workspace = tmp_path / "ws-auto-build"
    workspace.mkdir()
    make_executable(
        fake_bin / "podman",
        "#!/bin/sh\n"
        "printf 'cmd:%s %s\\n' \"$0\" \"$*\" >> \"${FAKE_PODMAN_LOG:?}\"\n"
        "if [ \"$1\" = image ] && [ \"$2\" = inspect ]; then\n"
        "  exit 1\n"
        "fi\n"
        "exit 0\n",
    )

    result = run(
        [str(AGENTIC_RESEARCHER), "--sandbox", "podman", "--tool", "pi", str(workspace)],
        base_env,
    )

    assert result.returncode == 0
    assert "Container image for podman was not found." in result.stdout
    assert "Building it now." in result.stdout
    podman_log = read_log(base_env["FAKE_PODMAN_LOG"])
    assert "image inspect agentic-researcher:latest" in podman_log
    assert "build --format docker -t agentic-researcher:latest" in podman_log
    assert "run --rm" in podman_log


def test_launcher_native_runs_host_tool_without_container(
    base_env: dict[str, str], fake_bin: Path, tmp_path: Path
) -> None:
    workspace = tmp_path / "ws-none"
    workspace.mkdir()
    tool_log = tmp_path / "codex-none.log"
    make_executable(
        fake_bin / "codex",
        "#!/bin/sh\n"
        "printf 'cwd:%s\\n' \"$PWD\" >> \"${FAKE_CODEX_LOG:?}\"\n"
        "printf 'args:%s\\n' \"$*\" >> \"${FAKE_CODEX_LOG:?}\"\n",
    )

    result = run(
        [
            str(AGENTIC_RESEARCHER),
            "--sandbox", "none",
            "--tool",
            "codex",
            "--model",
            "gpt-test",
            str(workspace),
        ],
        {**base_env, "FAKE_CODEX_LOG": str(tool_log)},
    )

    assert result.returncode == 0
    assert "Agentic Researcher - Codex CLI (No Sandbox)" in result.stdout
    assert "Sandboxed:      No (sandbox none; full host filesystem access)" in result.stdout
    assert "Job backend:    none" in result.stdout
    assert f"cwd:{workspace}" in tool_log.read_text()
    assert "args:--model gpt-test" in tool_log.read_text()
    setup_skill = workspace / ".agents" / "skills" / "setup_research_plan" / "SKILL.md"
    assert setup_skill.exists()
    assert "name: \"setup_research_plan\"" in setup_skill.read_text()
    codex_agent = workspace / ".codex" / "agents" / "gpu-job-runner.toml"
    assert codex_agent.exists()
    codex_agent_text = codex_agent.read_text()
    assert 'name = "gpu-job-runner"' in codex_agent_text
    assert 'model_reasoning_effort = "low"' in codex_agent_text
    assert "developer_instructions" in codex_agent_text
    experiment_logger = workspace / ".codex" / "agents" / "experiment-logger.toml"
    assert experiment_logger.exists()
    assert 'name = "experiment-logger"' in experiment_logger.read_text()
    assert not (workspace / ".agents" / "skills" / "experiment_log" / "SKILL.md").exists()
    codex_hook = workspace / ".codex" / "hooks" / "agentic-researcher-compaction.py"
    assert codex_hook.exists()
    assert not (workspace / ".agents" / "hooks" / "agentic-researcher-compaction-refresh.py").exists()
    codex_hook_text = codex_hook.read_text()
    assert "You have just experienced context compaction" in codex_hook_text
    assert "since the last compaction" in codex_hook_text
    assert "run_refresh" in codex_hook_text
    codex_hooks = json.loads((workspace / ".codex" / "hooks.json").read_text())
    codex_command = codex_hooks["hooks"]["SessionStart"][0]["hooks"][0]["command"]
    assert codex_hooks["hooks"]["SessionStart"][0]["matcher"] == "compact"
    assert "agentic-researcher-compaction.py" in codex_command
    assert str(REPO_ROOT / "scripts" / "ar-notes") in codex_command
    assert str(workspace / "AGENTS.md") in codex_command
    assert str(workspace) in codex_command
    assert read_log(base_env["FAKE_PODMAN_LOG"]) == ""
    assert read_log(base_env["FAKE_DOCKER_LOG"]) == ""


def test_launcher_native_codex_yolo_uses_current_codex_flag(
    base_env: dict[str, str], fake_bin: Path, tmp_path: Path
) -> None:
    workspace = tmp_path / "ws-codex-yolo"
    workspace.mkdir()
    tool_log = tmp_path / "codex-yolo.log"
    make_executable(
        fake_bin / "codex",
        "#!/bin/sh\n"
        "printf 'args:%s\\n' \"$*\" >> \"${FAKE_CODEX_LOG:?}\"\n",
    )

    result = run(
        [
            str(AGENTIC_RESEARCHER),
            "--sandbox",
            "none",
            "--tool",
            "codex",
            "--yolo",
            str(workspace),
        ],
        {**base_env, "FAKE_CODEX_LOG": str(tool_log)},
    )

    assert result.returncode == 0
    log_text = tool_log.read_text()
    assert "--dangerously-bypass-approvals-and-sandbox" in log_text
    assert "--full-auto" not in log_text


def test_launcher_falls_back_when_python3_on_path_is_not_executable(
    base_env: dict[str, str], fake_bin: Path, tmp_path: Path
) -> None:
    workspace = tmp_path / "ws-python-fallback"
    workspace.mkdir()
    make_executable(fake_bin / "codex", "#!/bin/sh\nexit 0\n")
    make_executable(
        fake_bin / "python3",
        "#!/bin/sh\n"
        "echo 'python3 blocked' >&2\n"
        "exit 126\n",
    )
    make_executable(
        fake_bin / "python",
        "#!/bin/sh\n"
        f"exec {shlex_quote(sys.executable)} \"$@\"\n",
    )

    result = run(
        [str(AGENTIC_RESEARCHER), "--sandbox", "none", "--tool", "codex", str(workspace)],
        base_env,
    )

    assert result.returncode == 0
    assert "Could not update Codex compaction hook settings" not in result.stdout + result.stderr
    hooks = json.loads((workspace / ".codex" / "hooks.json").read_text())
    command = hooks["hooks"]["SessionStart"][0]["hooks"][0]["command"]
    assert "agentic-researcher-compaction.py" in command


def test_launcher_requires_project_id_for_launch(
    base_env: dict[str, str], tmp_path: Path
) -> None:
    workspace = tmp_path / "ws-missing-project-id"
    workspace.mkdir()
    env = {**base_env}
    env.pop("AR_PROJECT_ID", None)

    result = run(
        [
            str(AGENTIC_RESEARCHER),
            "--sandbox", "none",
            "--tool",
            "codex",
            str(workspace),
        ],
        env,
    )

    assert result.returncode == 1
    assert "could not infer a project id" in result.stdout
    assert "agentic-researcher --project-id my-project-2026" in result.stdout


def test_launcher_infers_project_id_from_git_remote(
    base_env: dict[str, str], fake_bin: Path, tmp_path: Path
) -> None:
    workspace = tmp_path / "ws-remote-project"
    remote = tmp_path / "project.git"
    run(["git", "init", "--bare", str(remote)], base_env)
    run(["git", "init", str(workspace)], base_env)
    run(["git", "-C", str(workspace), "remote", "add", "origin", str(remote)], base_env)
    make_executable(fake_bin / "codex", "#!/bin/sh\nexit 0\n")
    env = {**base_env}
    env.pop("AR_PROJECT_ID", None)

    result = run(
        [
            str(AGENTIC_RESEARCHER),
            "--sandbox", "none",
            "--tool",
            "codex",
            str(workspace),
        ],
        env,
    )

    assert result.returncode == 0
    projects_root = Path(env["HOME"]) / ".cache" / "agentic-researcher" / "projects"
    projects = list(projects_root.iterdir())
    assert len(projects) == 1
    assert projects[0].name == "project"
    assert (
        projects[0]
        / "agentic-state"
        / ".agentic"
        / "agent-notes"
        / "all-agents"
        / "always-injected.md"
    ).exists()


def test_launcher_project_id_flag_overrides_missing_env(
    base_env: dict[str, str], fake_bin: Path, tmp_path: Path
) -> None:
    workspace = tmp_path / "ws-project-id-flag"
    workspace.mkdir()
    make_executable(fake_bin / "codex", "#!/bin/sh\nexit 0\n")
    env = {**base_env}
    env.pop("AR_PROJECT_ID", None)

    result = run(
        [
            str(AGENTIC_RESEARCHER),
            "--sandbox", "none",
            "--tool",
            "codex",
            "--project-id",
            "flag-project",
            str(workspace),
        ],
        env,
    )

    assert result.returncode == 0
    assert (Path(env["HOME"]) / ".cache" / "agentic-researcher" / "projects" / "flag-project" / "agentic-state").exists()


def test_launcher_compaction_hook_merge_preserves_existing_project_hooks(
    base_env: dict[str, str], fake_bin: Path, tmp_path: Path
) -> None:
    workspace = tmp_path / "ws-existing-hooks"
    workspace.mkdir()
    (workspace / ".codex").mkdir()
    (workspace / ".codex" / "hooks.json").write_text(
        json.dumps({
            "hooks": {
                "Stop": [
                    {
                        "hooks": [
                            {
                                "type": "command",
                                "command": "printf existing",
                            }
                        ]
                    }
                ]
            }
        }) + "\n"
    )
    make_executable(fake_bin / "codex", "#!/bin/sh\nexit 0\n")

    command = [
        str(AGENTIC_RESEARCHER),
        "--sandbox", "none",
        "--tool",
        "codex",
        str(workspace),
    ]
    env = {**base_env}
    result = run(command, env)
    result_again = run(command, env)

    assert result.returncode == 0
    assert result_again.returncode == 0
    hooks = json.loads((workspace / ".codex" / "hooks.json").read_text())
    assert hooks["hooks"]["Stop"][0]["hooks"][0]["command"] == "printf existing"
    session_start = hooks["hooks"]["SessionStart"]
    commands = [hook["command"] for group in session_start for hook in group["hooks"]]
    managed_commands = [cmd for cmd in commands if "agentic-researcher-compaction.py" in cmd]
    assert len(managed_commands) == 1


def test_build_command_rejects_none_sandbox(base_env: dict[str, str]) -> None:
    result = run([str(BUILD_SCRIPT), "--runtime", "none"], base_env)

    assert result.returncode == 1
    assert "Unsupported runtime: none" in result.stderr
    assert read_log(base_env["FAKE_PODMAN_LOG"]) == ""
    assert read_log(base_env["FAKE_DOCKER_LOG"]) == ""


def test_launcher_native_test_checks_rocm_when_nvidia_unavailable(
    base_env: dict[str, str], fake_bin: Path, tmp_path: Path
) -> None:
    workspace = tmp_path / "ws-rocm"
    workspace.mkdir()
    make_executable(fake_bin / "codex", "#!/bin/sh\nexit 0\n")
    make_executable(fake_bin / "nvidia-smi", "#!/bin/sh\nexit 1\n")
    make_executable(fake_bin / "rocm-smi", "#!/bin/sh\necho 'ROCm GPU'; exit 0\n")

    result = run(
        [
            str(AGENTIC_RESEARCHER),
            "--sandbox", "none",
            "--tool",
            "codex",
            "--test",
            str(workspace),
        ],
        {**base_env},
    )

    assert result.returncode == 0
    assert "GPU visible via rocm-smi" in result.stdout


def test_native_cluster_run_backend_renders_project_skill(
    base_env: dict[str, str], fake_bin: Path, tmp_path: Path
) -> None:
    workspace = tmp_path / "ws-cluster"
    workspace.mkdir()
    make_executable(fake_bin / "codex", "#!/bin/sh\nexit 0\n")
    make_executable(
        fake_bin / "cluster-run",
        "#!/bin/sh\n"
        "case \"$1\" in\n"
        "  --help|-h|help) echo 'cluster-run help'; exit 0 ;;\n"
        "  status) echo 'cluster-run status'; exit 0 ;;\n"
        "esac\n"
        "echo 'cluster-run fake'; exit 0\n",
    )

    result = run(
        [
            str(AGENTIC_RESEARCHER),
            "--sandbox", "none",
            "--tool",
            "codex",
            "--optional-skill",
            "cluster-run",
            str(workspace),
        ],
        base_env,
    )

    assert result.returncode == 0
    skill_path = workspace / ".agents" / "skills" / "cluster-run" / "SKILL.md"
    assert skill_path.exists()
    skill_text = skill_path.read_text()
    assert "Generated by agentic-researcher" in skill_text
    assert "cluster-run status" in skill_text
    instruction_text = (workspace / "AGENTS.md").read_text()
    assert "AGENTIC-RESEARCHER-SKILL-INSTRUCTIONS-START cluster-run" in instruction_text
    assert "Job Backend: cluster-run" in instruction_text
    assert (workspace / ".agents" / "skills" / "retro" / "SKILL.md").exists()
    experiment_agent = workspace / ".codex" / "agents" / "experiment-runner.toml"
    assert experiment_agent.exists()
    assert 'model_reasoning_effort = "medium"' in experiment_agent.read_text()
    assert (workspace / ".codex" / "agents" / "experiment-logger.toml").exists()


def test_gpu_backend_flag_is_removed(base_env: dict[str, str], tmp_path: Path) -> None:
    workspace = tmp_path / "ws-removed-gpu-backend"
    workspace.mkdir()

    result = run(
        [
            str(AGENTIC_RESEARCHER),
            "--gpu-backend",
            "cluster-run",
            str(workspace),
        ],
        base_env,
    )

    assert result.returncode == 1
    assert "--gpu-backend has been removed" in result.stdout
    assert "--optional-skill cluster-run" in result.stdout


def test_remote_run_optional_skill_checks_its_own_sandbox_requirement(
    base_env: dict[str, str], tmp_path: Path
) -> None:
    workspace = tmp_path / "ws-remote-run-preflight"
    workspace.mkdir()

    result = run(
        [
            str(AGENTIC_RESEARCHER),
            "--sandbox",
            "none",
            "--optional-skill",
            "remote-run",
            str(workspace),
        ],
        {**base_env},
    )

    assert result.returncode == 1
    assert "remote-run optional skill requires --sandbox apptainer" in result.stderr


def test_native_optional_skill_renders_skill_and_instruction_overlay(
    base_env: dict[str, str], fake_bin: Path, tmp_path: Path
) -> None:
    workspace = tmp_path / "ws-optional-skill"
    workspace.mkdir()
    make_executable(fake_bin / "codex", "#!/bin/sh\nexit 0\n")
    make_executable(fake_bin / "cluster-run", "#!/bin/sh\n[ \"$1\" = --help ] && exit 0\nexit 0\n")

    result = run(
        [
            str(AGENTIC_RESEARCHER),
            "--sandbox", "none",
            "--tool",
            "codex",
            "--optional-skill",
            "cluster-run",
            str(workspace),
        ],
        {**base_env},
    )

    assert result.returncode == 0
    assert (workspace / ".agents" / "skills" / "cluster-run" / "SKILL.md").exists()
    instruction_text = (workspace / "AGENTS.md").read_text()
    assert "AGENTIC-RESEARCHER-SKILL-INSTRUCTIONS-START cluster-run" in instruction_text
    assert "The `cluster-run` optional skill is active" in instruction_text


def test_native_claude_cluster_run_backend_uses_claude_skills_dir(
    base_env: dict[str, str], fake_bin: Path, tmp_path: Path
) -> None:
    workspace = tmp_path / "ws-claude-cluster"
    workspace.mkdir()
    make_executable(fake_bin / "claude", "#!/bin/sh\nexit 0\n")
    make_executable(fake_bin / "cluster-run", "#!/bin/sh\n[ \"$1\" = --help ] && exit 0\nexit 0\n")

    result = run(
        [
            str(AGENTIC_RESEARCHER),
            "--sandbox", "none",
            "--tool",
            "claude",
            "--optional-skill",
            "cluster-run",
            str(workspace),
        ],
        base_env,
    )

    assert result.returncode == 0
    assert (workspace / ".claude" / "skills" / "cluster-run" / "SKILL.md").exists()
    assert (workspace / ".claude" / "skills" / "setup_research_plan" / "SKILL.md").exists()
    claude_agent = workspace / ".claude" / "agents" / "gpu-job-runner.md"
    assert claude_agent.exists()
    assert "codex_reasoning_effort" not in claude_agent.read_text()
    claude_hook = workspace / ".claude" / "hooks" / "agentic-researcher-compaction.py"
    assert claude_hook.exists()
    assert not (workspace / ".agents" / "hooks" / "agentic-researcher-compaction-refresh.py").exists()
    claude_hook_text = claude_hook.read_text()
    assert "You have just experienced context compaction" in claude_hook_text
    assert "since the last compaction" in claude_hook_text
    assert "run_refresh" in claude_hook_text
    claude_settings = json.loads((workspace / ".claude" / "settings.local.json").read_text())
    claude_command = claude_settings["hooks"]["SessionStart"][0]["hooks"][0]["command"]
    assert claude_settings["hooks"]["SessionStart"][0]["matcher"] == "compact"
    assert "agentic-researcher-compaction.py" in claude_command
    assert str(REPO_ROOT / "scripts" / "ar-notes") in claude_command
    assert str(workspace / "CLAUDE.md") in claude_command
    assert str(workspace) in claude_command


def test_native_gemini_cluster_run_backend_uses_gemini_skills_dir(
    base_env: dict[str, str], fake_bin: Path, tmp_path: Path
) -> None:
    workspace = tmp_path / "ws-gemini-cluster"
    workspace.mkdir()
    make_executable(fake_bin / "gemini", "#!/bin/sh\nexit 0\n")
    make_executable(fake_bin / "cluster-run", "#!/bin/sh\n[ \"$1\" = --help ] && exit 0\nexit 0\n")

    result = run(
        [
            str(AGENTIC_RESEARCHER),
            "--sandbox", "none",
            "--tool",
            "gemini",
            "--optional-skill",
            "cluster-run",
            str(workspace),
        ],
        base_env,
    )

    assert result.returncode == 0
    assert (workspace / ".gemini" / "skills" / "cluster-run" / "SKILL.md").exists()
    assert (workspace / ".gemini" / "skills" / "setup_research_plan" / "SKILL.md").exists()
    gemini_agent = workspace / ".gemini" / "agents" / "gpu-job-runner.md"
    assert gemini_agent.exists()
    assert "codex_reasoning_effort" not in gemini_agent.read_text()
    assert not (workspace / ".agents" / "skills" / "cluster-run" / "SKILL.md").exists()
    gemini_hook = workspace / ".gemini" / "hooks" / "agentic-researcher-compaction.py"
    assert gemini_hook.exists()
    assert not (workspace / ".agents" / "hooks" / "agentic-researcher-compaction-refresh.py").exists()
    gemini_hook_text = gemini_hook.read_text()
    assert "You have just experienced context compaction" in gemini_hook_text
    assert "since the last compaction" in gemini_hook_text
    assert "run_refresh" in gemini_hook_text
    gemini_settings = json.loads((workspace / ".gemini" / "settings.json").read_text())
    precompress_command = gemini_settings["hooks"]["PreCompress"][0]["hooks"][0]["command"]
    before_model_command = gemini_settings["hooks"]["BeforeModel"][0]["hooks"][0]["command"]
    assert "agentic-researcher-compaction.py' mark" in precompress_command
    assert "agentic-researcher-compaction.py' inject" in before_model_command
    assert str(REPO_ROOT / "scripts" / "ar-notes") in precompress_command
    assert str(REPO_ROOT / "scripts" / "ar-notes") in before_model_command
    assert str(workspace / "GEMINI.md") in precompress_command
    assert str(workspace / "GEMINI.md") in before_model_command


def test_native_opencode_cluster_run_backend_uses_opencode_skills_dir(
    base_env: dict[str, str], fake_bin: Path, tmp_path: Path
) -> None:
    workspace = tmp_path / "ws-opencode-cluster"
    workspace.mkdir()
    make_executable(fake_bin / "opencode", "#!/bin/sh\nexit 0\n")
    make_executable(fake_bin / "cluster-run", "#!/bin/sh\n[ \"$1\" = --help ] && exit 0\nexit 0\n")

    result = run(
        [
            str(AGENTIC_RESEARCHER),
            "--sandbox", "none",
            "--tool",
            "opencode",
            "--optional-skill",
            "cluster-run",
            str(workspace),
        ],
        base_env,
    )

    assert result.returncode == 0
    assert (workspace / ".opencode" / "skills" / "cluster-run" / "SKILL.md").exists()
    assert (workspace / ".opencode" / "skills" / "setup_research_plan" / "SKILL.md").exists()
    opencode_agent = workspace / ".opencode" / "agents" / "gpu-job-runner.md"
    assert opencode_agent.exists()
    opencode_agent_text = opencode_agent.read_text()
    assert "mode: subagent" in opencode_agent_text
    assert "codex_reasoning_effort" not in opencode_agent_text
    assert not (workspace / ".agents" / "skills" / "cluster-run" / "SKILL.md").exists()
    opencode_plugin = workspace / ".opencode" / "plugins" / "agentic-researcher-compaction.ts"
    assert opencode_plugin.exists()
    opencode_plugin_text = opencode_plugin.read_text()
    assert "experimental.session.compacting" in opencode_plugin_text
    assert "You have just experienced context compaction" in opencode_plugin_text
    assert "since the last compaction" in opencode_plugin_text
    assert "execFileSync" in opencode_plugin_text
    assert str(REPO_ROOT / "scripts" / "ar-notes") in opencode_plugin_text
    assert str(workspace / "AGENTS.md") in opencode_plugin_text


def test_install_script_auto_detects_podman_when_docker_is_absent(
    base_env: dict[str, str], fake_bin: Path, tmp_path: Path
) -> None:
    (fake_bin / "docker").unlink()
    install_dir = tmp_path / "install-auto"
    bin_dir = tmp_path / "launcher-bin-auto"
    config_dir = tmp_path / "config-auto"

    result = run(
        [
            str(INSTALL_SCRIPT),
            "--install-dir",
            str(install_dir),
            "--bin-dir",
            str(bin_dir),
            "--write-config",
            "--force",
        ],
        {**base_env, "XDG_CONFIG_HOME": str(config_dir)},
    )

    assert result.returncode == 0
    config_text = (config_dir / "agentic-researcher" / "config.sh").read_text()
    assert 'AR_SANDBOX="podman"' in config_text
    assert 'AR_AUTO_BUILD="true"' in config_text
    assert "Docker not found, falling back to Podman." in result.stdout
    assert "Building Podman container" not in result.stdout
    assert read_log(base_env["FAKE_PODMAN_LOG"]) == ""
    assert read_log(base_env["FAKE_DOCKER_LOG"]) == ""


def test_install_script_accepts_native_runtime(base_env: dict[str, str], tmp_path: Path) -> None:
    install_dir = tmp_path / "install-none"
    bin_dir = tmp_path / "launcher-bin-none"
    config_dir = tmp_path / "config-none"

    result = run(
        [
            str(INSTALL_SCRIPT),
            "--install-dir",
            str(install_dir),
            "--bin-dir",
            str(bin_dir),
            "--sandbox",
            "none",
            "--tool",
            "codex",
            "--write-config",
            "--force",
        ],
        {**base_env, "XDG_CONFIG_HOME": str(config_dir)},
    )

    assert result.returncode == 0
    config_text = (config_dir / "agentic-researcher" / "config.sh").read_text()
    assert 'AR_SANDBOX="none"' in config_text
    assert 'AR_OPTIONAL_SKILLS=""' in config_text
    assert 'AR_AUTO_BUILD="true"' in config_text
    assert read_log(base_env["FAKE_PODMAN_LOG"]) == ""
    assert read_log(base_env["FAKE_DOCKER_LOG"]) == ""


# ── pi (@earendil-works/pi-coding-agent) tool support ────────────────────

def test_launcher_podman_runs_pi_tool(base_env: dict[str, str], tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()

    result = run(
        [str(AGENTIC_RESEARCHER), "--sandbox", "podman", "--tool", "pi", str(workspace)],
        base_env,
    )

    assert result.returncode == 0
    assert "Starting pi" in result.stdout
    podman_log = read_log(base_env["FAKE_PODMAN_LOG"])
    assert "run --rm" in podman_log
    assert "SANDBOX_TOOL=pi" in podman_log
    assert f"{REPO_ROOT}:/opt/agentic-researcher:ro" in podman_log
    assert "AR_NOTES_CLI=/opt/agentic-researcher/scripts/ar-notes" in podman_log
    # pi reads AGENTS.md; the launcher must seed it into the workspace.
    assert (workspace / "AGENTS.md").exists()
    # pi uses the shared agent-compatible project skill path.
    for skill in ("setup_research_plan", "retro"):
        assert (workspace / ".agents" / "skills" / skill / "SKILL.md").exists()
    assert not (workspace / ".agents" / "skills" / "experiment_log" / "SKILL.md").exists()
    pi_extension = workspace / ".pi" / "extensions" / "agentic-researcher-compaction.ts"
    assert pi_extension.exists()
    assert not (workspace / ".agents" / "hooks" / "agentic-researcher-compaction-refresh.py").exists()
    pi_extension_text = pi_extension.read_text()
    assert 'pi.on("session_compact"' in pi_extension_text
    assert "You have just experienced context compaction" in pi_extension_text
    assert "since the last compaction" in pi_extension_text
    assert "execFileSync" in pi_extension_text
    assert "/opt/agentic-researcher/scripts/ar-notes" in pi_extension_text
    assert "/workspace/AGENTS.md" in pi_extension_text
    assert read_log(base_env["FAKE_DOCKER_LOG"]) == ""


def test_pi_translates_resume_to_session_and_warns_on_yolo(
    base_env: dict[str, str], tmp_path: Path
) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()

    result = run(
        [
            str(AGENTIC_RESEARCHER),
            "--sandbox", "podman",
            "--tool",
            "pi",
            "--debug-launch",
            "--resume",
            "ABC123",
            "--yolo",
            str(workspace),
        ],
        base_env,
    )

    assert result.returncode == 0
    # pi has no bare --resume ID; it maps to --session ID.
    assert "--session ABC123" in result.stdout
    # --debug-launch enables pi's verbose startup.
    assert "--verbose" in result.stdout
    assert "-e /workspace/.pi/extensions/agentic-researcher-compaction.ts" in result.stdout
    # pi has no permission system, so --yolo is a no-op with a warning.
    assert "--yolo has no effect in pi mode" in result.stdout


def test_pi_apptainer_bind_and_config_store_wiring() -> None:
    launcher_text = AGENTIC_RESEARCHER.read_text()
    pi_adapter = (CLI_ADAPTER_DIR / "pi.sh").read_text()
    # Apptainer path binds the host pi config dir (~/.pi) into the sandbox.
    assert 'BIND_ARGS+=(--bind "$PI_STATE_DIR:$AR_SANDBOX_HOME/.pi")' in pi_adapter
    assert 'PI_STATE_DIR="$HOME/.pi"' in pi_adapter
    # Docker/Podman path seeds the per-tool dir inside the single config store.
    assert '"$AR_CONFIG_STORE/.pi/agent"' in pi_adapter
    # pi uses AGENTS.md as its instruction file.
    assert 'printf \'%s\\n\' "AGENTS.md"' in pi_adapter
    # pi shares the generated project-skill setup.
    assert "setup_project_skills" in launcher_text


def test_launcher_has_no_legacy_slash_command_wiring() -> None:
    launcher_text = AGENTIC_RESEARCHER.read_text()

    assert "SCRIPT_DIR/commands" not in launcher_text
    assert ".claude/commands" not in launcher_text
    assert "OPENCODE_COMMANDS_DIR" not in launcher_text
