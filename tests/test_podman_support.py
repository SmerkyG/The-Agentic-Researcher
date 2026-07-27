import json
import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
AGENTIC_TEAM = REPO_ROOT / "agentic-team"
BUILD_SCRIPT = REPO_ROOT / "container" / "build.sh"
INSTALL_SCRIPT = REPO_ROOT / "scripts" / "install.sh"
FIRST_SETUP_SCRIPT = REPO_ROOT / "scripts" / "first-setup.sh"
CLEANUP_SCRIPT = REPO_ROOT / "scripts" / "cleanup.sh"
CLI_ADAPTER_DIR = REPO_ROOT / "scripts" / "lib" / "cli"
LAUNCHER_LIB_DIR = REPO_ROOT / "scripts" / "lib" / "launcher"
SANDBOX_LIB_DIR = REPO_ROOT / "scripts" / "lib" / "sandbox"
REMOTE_RUN_LAUNCHER_DIR = REPO_ROOT / "capabilities" / "remote-run" / "launcher"
REAL_GIT = shutil.which("git")


def make_executable(path: Path, content: str) -> None:
    path.write_text(content)
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def init_work_branch_workspace(path: Path, work_branch: str = "kernel-search") -> None:
    if REAL_GIT is None:
        raise RuntimeError("git is required for tests")
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run([REAL_GIT, "init", str(path)], check=True, capture_output=True, text=True)
    subprocess.run([REAL_GIT, "-C", str(path), "config", "user.name", "Test User"], check=True)
    subprocess.run([REAL_GIT, "-C", str(path), "config", "user.email", "test@example.com"], check=True)
    (path / "README.md").write_text("# Test Workspace\n")
    subprocess.run([REAL_GIT, "-C", str(path), "add", "README.md"], check=True)
    subprocess.run([REAL_GIT, "-C", str(path), "commit", "-m", "init"], check=True, capture_output=True, text=True)
    subprocess.run([REAL_GIT, "-C", str(path), "checkout", "-B", work_branch], check=True, capture_output=True, text=True)


def at_launch_args(workspace: Path, work_name: str = "kernel-search", source_ref: str = "kernel-search") -> list[str]:
    return [
        str(workspace.parent / f"{workspace.name}-at"),
        work_name,
        "--from",
        source_ref,
        "--project-dir",
        str(workspace),
        "--branch",
        source_ref,
    ]


def client_dir(workspace: Path, client: str, work_name: str = "kernel-search") -> Path:
    return workspace.parent / f"{workspace.name}-at" / work_name / "client" / client


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
    env.pop("CODEX_HOME", None)
    env["AR_MAIN_AGENT"] = "research-coordinator"
    env["AR_WORK_BRANCH"] = "kernel-search"
    env["AR_NOTES_AUTO_REFRESH"] = "false"
    env["AR_CAPABILITIES"] = "none"
    env["UV_CACHE_DIR"] = str(REPO_ROOT / ".pytest_cache" / "uv" / "cache")
    env["UV_PYTHON_INSTALL_DIR"] = str(REPO_ROOT / ".pytest_cache" / "uv" / "python")
    env["UV_TOOL_DIR"] = str(REPO_ROOT / ".pytest_cache" / "uv" / "tools")
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
    config_dir = xdg_config_home / "agentic-team"
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
    assert "build --format docker -t agentic-team:latest" in podman_log
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


def test_sandbox_implementations_stay_out_of_generic_launcher_files() -> None:
    instructions = (LAUNCHER_LIB_DIR / "instructions.sh").read_text()
    storage = (LAUNCHER_LIB_DIR / "storage.sh").read_text()
    build = BUILD_SCRIPT.read_text()
    apptainer = (SANDBOX_LIB_DIR / "apptainer.sh").read_text()

    assert "APPTAINER_" not in instructions
    assert "APPTAINER_" not in storage
    assert "apptainer build" not in build
    assert "sandbox_call_required build_image" in build
    assert "sandbox_apptainer_setup_storage" in apptainer
    assert "apptainer build" in apptainer


def test_remote_run_owns_its_dispatcher() -> None:
    dispatcher = REMOTE_RUN_LAUNCHER_DIR / "dispatcher.sh"
    start = (REMOTE_RUN_LAUNCHER_DIR / "start.sh").read_text()
    dispatcher_text = dispatcher.read_text()

    assert dispatcher.is_file()
    assert "srun --overlap" in dispatcher_text
    assert "STORAGE_NAMES" in dispatcher_text
    assert "UV_CACHE_DIR:/uv-cache" not in dispatcher_text
    assert "capabilities/remote-run/launcher/dispatcher.sh" in start
    assert not (REPO_ROOT / "scripts" / "dispatcher.sh").exists()


def test_launcher_apply_defaults_keeps_real_auth_defaults(base_env: dict[str, str]) -> None:
    result = run(
        [str(AGENTIC_TEAM), "--help"],
        {**base_env, "AR_CLI": "claude"},
    )

    assert result.returncode == 0
    claude_adapter = (CLI_ADAPTER_DIR / "claude.sh").read_text()
    opencode_adapter = (CLI_ADAPTER_DIR / "opencode.sh").read_text()
    assert 'AR_AUTH_MODE="${AR_AUTH_MODE:-oauth}"' in claude_adapter
    assert 'AR_API_KEY_ENV="${AR_API_KEY_ENV:-ANTHROPIC_API_KEY}"' in claude_adapter
    assert 'AR_AUTH_MODE="${AR_AUTH_MODE:-cli-tool}"' in opencode_adapter


def test_launcher_without_arguments_shows_help_without_creating_workspace(
    base_env: dict[str, str],
) -> None:
    home = Path(base_env["HOME"])
    workspace = home.parent / f"{home.name}-at"

    result = subprocess.run(
        [str(AGENTIC_TEAM)],
        cwd=home,
        env=base_env,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 2
    assert "agentic-team requires a project/workspace argument" in result.stderr
    assert "Usage:" in result.stderr
    assert not workspace.exists()


def test_setup_opencode_reads_api_key_from_configured_env_var(base_env: dict[str, str], tmp_path: Path) -> None:
    opencode_adapter = (CLI_ADAPTER_DIR / "opencode.sh").read_text()
    assert 'local api_key_var="${AR_API_KEY_ENV:-OPENAI_API_KEY}"' in opencode_adapter
    assert 'local api_key="${!api_key_var:-}"' in opencode_adapter


def test_claude_adapter_handles_apptainer_key_forwarding(base_env: dict[str, str]) -> None:
    registry_text = (LAUNCHER_LIB_DIR / "registry.sh").read_text()
    claude_adapter = (CLI_ADAPTER_DIR / "claude.sh").read_text()
    assert "append_env_arg_from_host_as" in registry_text
    assert 'append_env_arg_from_host_as "ANTHROPIC_API_KEY" "${AR_API_KEY_ENV:-ANTHROPIC_API_KEY}"' in claude_adapter


def test_claude_workspace_guard_lives_in_claude_adapter() -> None:
    launcher_text = AGENTIC_TEAM.read_text()
    claude_adapter = (CLI_ADAPTER_DIR / "claude.sh").read_text()

    assert "Cannot sandbox Claude config directories" not in launcher_text
    assert "Cannot sandbox Claude config directories" in claude_adapter


def test_claude_rejects_own_config_as_workspace(base_env: dict[str, str]) -> None:
    workspace = Path(base_env["HOME"]) / ".claude"
    init_work_branch_workspace(workspace)

    result = run(
        [str(AGENTIC_TEAM), "--sandbox", "none", "--cli", "claude", *at_launch_args(workspace)],
        base_env,
    )

    assert result.returncode != 0
    assert "Cannot sandbox Claude config directories" in result.stdout + result.stderr


def test_non_claude_cli_does_not_inherit_claude_workspace_guard(base_env: dict[str, str]) -> None:
    fake_bin = Path(base_env["PATH"].split(":", maxsplit=1)[0])
    make_executable(fake_bin / "codex", "#!/bin/sh\nexit 0\n")
    workspace = Path(base_env["HOME"]) / ".claude"
    init_work_branch_workspace(workspace)

    result = run(
        [str(AGENTIC_TEAM), "--sandbox", "none", "--cli", "codex", *at_launch_args(workspace)],
        base_env,
    )

    assert "Cannot sandbox Claude config directories" not in result.stdout + result.stderr
    assert result.returncode == 0


def test_install_help_mentions_xdg_config_path(base_env: dict[str, str]) -> None:
    result = run([str(INSTALL_SCRIPT), "--help"], base_env)

    assert result.returncode == 0
    assert "${XDG_CONFIG_HOME:-$HOME/.config}/agentic-team/config.sh" in result.stdout


def test_setup_writes_config_to_xdg_config_home(base_env: dict[str, str], tmp_path: Path) -> None:
    xdg_config_home = tmp_path / "xdg-config"
    result = run(
        [str(FIRST_SETUP_SCRIPT)],
        {**base_env, "XDG_CONFIG_HOME": str(xdg_config_home)},
        input="1\n1\n\n\n\n\n\n\n\ngeneral\n",
    )

    assert result.returncode == 0
    config_path = xdg_config_home / "agentic-team" / "config.sh"
    assert config_path.exists()
    config_text = config_path.read_text()
    assert 'AR_ORG_NOTES_REPO=""' in config_text
    assert 'AR_MAIN_AGENT="general"' in config_text
    assert not (Path(base_env["HOME"]) / ".config" / "agentic-team" / "config.sh").exists()


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
    assert (bin_dir / "agentic-team").is_symlink()
    config_text = (config_dir / "agentic-team" / "config.sh").read_text()
    assert 'AR_SANDBOX="podman"' in config_text
    assert 'AR_AUTO_BUILD="true"' in config_text
    assert read_log(base_env["FAKE_PODMAN_LOG"]) == ""
    assert read_log(base_env["FAKE_DOCKER_LOG"]) == ""


def test_build_command_auto_detects_podman_when_docker_is_absent(
    base_env: dict[str, str], fake_bin: Path
) -> None:
    (fake_bin / "docker").unlink()

    result = run([str(BUILD_SCRIPT)], base_env)

    assert result.returncode == 0
    assert "Docker not found, falling back to Podman." in result.stdout
    assert "Building Podman container" in result.stdout
    assert "build --format docker -t agentic-team:latest" in read_log(base_env["FAKE_PODMAN_LOG"])
    assert read_log(base_env["FAKE_DOCKER_LOG"]) == ""


def test_launcher_podman_test_mode_overrides_entrypoint(base_env: dict[str, str]) -> None:
    result = run([str(AGENTIC_TEAM), "--sandbox", "podman", "--cli", "codex", "--test"], base_env)

    assert result.returncode == 0
    podman_log = read_log(base_env["FAKE_PODMAN_LOG"])
    assert "run --rm" in podman_log
    assert "-it" not in podman_log
    assert "--userns keep-id" in podman_log
    assert ":/agent-home" in podman_log
    assert f"{REPO_ROOT}:/opt/agentic-team:ro" in podman_log
    assert "AR_SANDBOX=podman" in podman_log
    assert "AR_INSTALL_DIR=/opt/agentic-team" in podman_log
    assert "AR_TOOL_PATH=" in podman_log
    assert "AR_WORKFLOW_PATH=" in podman_log
    assert "/opt/agentic-team/capabilities/imperative-workflows/package" in podman_log
    assert "/opt/agentic-team/capabilities/research-coordinator/package" in podman_log
    assert "PATH=" in podman_log
    assert "/opt/agentic-team/scripts/bin" in podman_log
    assert "/opt/agentic-team/scripts/package" in podman_log
    assert "/opt/agentic-team/scripts/lib/commands" in podman_log
    assert "--entrypoint /bin/bash" in podman_log
    assert "/test_sandbox.sh" in podman_log


def test_configured_storage_dirs_mount_and_export_in_podman(
    base_env: dict[str, str], tmp_path: Path
) -> None:
    xdg_config_home = tmp_path / "xdg-config-storage"
    model_cache = tmp_path / "shared" / "models"
    triton_cache = tmp_path / "local" / "triton"
    write_xdg_config(
        xdg_config_home,
        "AR_STORAGE_DIRS=(\n"
        f'    "MY_MODEL_CACHE={model_cache}"\n'
        f'    "TRITON_CACHE_DIR={triton_cache}"\n'
        ")\n",
    )

    result = run(
        [str(AGENTIC_TEAM), "--sandbox", "podman", "--cli", "codex", "--test"],
        {**base_env, "XDG_CONFIG_HOME": str(xdg_config_home)},
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert model_cache.is_dir()
    assert triton_cache.is_dir()
    podman_log = read_log(base_env["FAKE_PODMAN_LOG"])
    assert f"-v {model_cache}:/agent-storage/MY_MODEL_CACHE" in podman_log
    assert "-e MY_MODEL_CACHE=/agent-storage/MY_MODEL_CACHE" in podman_log
    assert f"-v {triton_cache}:/agent-storage/TRITON_CACHE_DIR" in podman_log
    assert "-e TRITON_CACHE_DIR=/agent-storage/TRITON_CACHE_DIR" in podman_log


def test_launcher_auto_builds_missing_podman_image(
    base_env: dict[str, str], fake_bin: Path, tmp_path: Path
) -> None:
    workspace = tmp_path / "ws-auto-build"
    init_work_branch_workspace(workspace)
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
        [str(AGENTIC_TEAM), "--sandbox", "podman", "--cli", "pi", *at_launch_args(workspace)],
        base_env,
    )

    assert result.returncode == 0
    assert "Container image for podman was not found." in result.stdout
    assert "Building it now." in result.stdout
    podman_log = read_log(base_env["FAKE_PODMAN_LOG"])
    assert "image inspect agentic-team:latest" in podman_log
    assert "build --format docker -t agentic-team:latest" in podman_log
    assert "run --rm" in podman_log


def test_launcher_native_runs_host_cli__without_container(
    base_env: dict[str, str], fake_bin: Path, tmp_path: Path
) -> None:
    workspace = tmp_path / "ws-none"
    init_work_branch_workspace(workspace)
    cli__log = tmp_path / "codex-none.log"
    make_executable(
        fake_bin / "codex",
        "#!/bin/sh\n"
        "printf 'cwd:%s\\n' \"$PWD\" >> \"${FAKE_CODEX_LOG:?}\"\n"
        "printf 'args:%s\\n' \"$*\" >> \"${FAKE_CODEX_LOG:?}\"\n"
        "printf 'uv_cache:%s\\n' \"${UV_CACHE_DIR-}\" >> \"${FAKE_CODEX_LOG:?}\"\n"
        "printf 'uv_python:%s\\n' \"${UV_PYTHON_INSTALL_DIR-}\" >> \"${FAKE_CODEX_LOG:?}\"\n"
        "printf 'uv_tools:%s\\n' \"${UV_TOOL_DIR-}\" >> \"${FAKE_CODEX_LOG:?}\"\n"
        "printf 'artifacts:%s\\n' \"${AR_ARTIFACTS_DIR-}\" >> \"${FAKE_CODEX_LOG:?}\"\n"
        "printf 'workflow_path:%s\\n' \"${AR_WORKFLOW_PATH-}\" >> \"${FAKE_CODEX_LOG:?}\"\n"
        "printf 'branch_snapshot:%s\\n' \"$(command -v branch-snapshot)\" >> \"${FAKE_CODEX_LOG:?}\"\n",
    )
    native_env = {**base_env, "FAKE_CODEX_LOG": str(cli__log)}
    for key in ("UV_CACHE_DIR", "UV_PYTHON_INSTALL_DIR", "UV_TOOL_DIR"):
        native_env.pop(key, None)

    result = run(
        [
            str(AGENTIC_TEAM),
            "--sandbox", "none",
            "--cli",
            "codex",
            "--model",
            "gpt-test",
            *at_launch_args(workspace),
        ],
        native_env,
    )

    assert result.returncode == 0
    assert "Agentic Team - Codex CLI (No Sandbox)" in result.stdout
    assert "Sandboxed:      No (sandbox none; full host filesystem access)" in result.stdout
    assert "Job backend:    none" in result.stdout
    assert "UV Cache:       uv default (native mode)" in result.stdout
    expected_artifacts = workspace.parent / "ws-none-at" / "artifacts" / "project"
    assert f"Artifacts:      {expected_artifacts}" in result.stdout
    assert expected_artifacts.is_dir()
    cli__log_text = cli__log.read_text()
    assert f"cwd:{workspace}" in cli__log_text
    assert "--model gpt-test" in cli__log_text
    assert "mcp_servers.agentic_tools" not in cli__log_text
    assert "agentic-tools-mcp" not in cli__log_text
    assert "mcp_servers.agentic_workflows.command=" in cli__log_text
    assert "agentic-team-client" in cli__log_text
    assert "exec-workflow-mcp" in cli__log_text
    assert "mcp_servers.agentic_workflows.env_vars=" in cli__log_text
    assert '"AR_TOOL_PATH"' in cli__log_text
    assert '"AR_WORKFLOW_PATH"' in cli__log_text
    assert '"AR_RUNTIME_ROOT"' in cli__log_text
    assert '"AR_WORK_STATE_DIR"' in cli__log_text
    assert '"AR_ARTIFACTS_DIR"' in cli__log_text
    assert "mcp_servers.agentic_workflows.required=true" in cli__log_text
    assert "uv_cache:\n" in cli__log_text
    assert "uv_python:\n" in cli__log_text
    assert "uv_tools:\n" in cli__log_text
    assert f"artifacts:{expected_artifacts}" in cli__log_text
    assert f"{REPO_ROOT}/capabilities/imperative-workflows/package" in cli__log_text
    assert f"{REPO_ROOT}/capabilities/research-coordinator/package" in cli__log_text
    assert "capabilities/branch/bin/branch-snapshot" in cli__log_text
    assert not (Path(native_env["HOME"]) / ".cache" / "agentic-team" / "uv").exists()
    research_skill = workspace / ".agents" / "skills" / "do_research" / "SKILL.md"
    assert research_skill.exists()
    assert "name: do_research" in research_skill.read_text()
    codex_agent = workspace / ".codex" / "agents" / "research-finalizer.toml"
    assert codex_agent.exists()
    codex_agent_text = codex_agent.read_text()
    assert 'name = "research-finalizer"' in codex_agent_text
    assert 'model_reasoning_effort = "low"' in codex_agent_text
    assert "developer_instructions" in codex_agent_text
    assert "Call the `start_workflow` tool" in codex_agent_text
    assert (
        "agentic_workflows.research.research_finalizer:ResearchFinalizer"
        in codex_agent_text
    )
    assert "Do not invoke `imperative-workflows-callback` through a shell" in codex_agent_text
    assert not (workspace / ".agents" / "skills" / "experiment_log" / "SKILL.md").exists()
    context_path = client_dir(workspace, "codex") / "context.json"
    context = json.loads(context_path.read_text())
    assert context["project_dir"] == str(workspace)
    assert context["client"] == "codex"
    assert context["commands"]["workflow_mcp"].endswith("imperative-workflows-mcp")
    assert context["environment"]["AR_CLIENT_CONTEXT"] == str(context_path)
    assert not (workspace / ".agents" / "hooks" / "agentic-team-compaction-refresh.py").exists()
    assert not (workspace / ".codex" / "hooks").exists()
    assert not (workspace / ".codex" / "hooks.json").exists()
    codex_hooks = json.loads((Path(native_env["HOME"]) / ".codex" / "hooks.json").read_text())
    post_compact_hook = codex_hooks["hooks"]["PostCompact"][0]
    post_compact_command = post_compact_hook["hooks"][0]["command"]
    post_tool_hook = codex_hooks["hooks"]["PostToolUse"][0]
    post_tool_command = post_tool_hook["hooks"][0]["command"]
    assert post_compact_hook["matcher"] == "manual|auto"
    assert post_tool_hook["matcher"] == "*"
    assert codex_hooks["hooks"]["UserPromptSubmit"] == []
    assert not codex_hooks["hooks"]["SessionStart"]
    assert "agentic-team-client hook codex-post-compact --client codex" == post_compact_command
    assert "agentic-team-client hook codex-post-tool --client codex" == post_tool_command
    assert "codex-post-tool" in post_tool_command
    assert read_log(base_env["FAKE_PODMAN_LOG"]) == ""
    assert read_log(base_env["FAKE_DOCKER_LOG"]) == ""


def test_configured_storage_dirs_export_host_paths_in_native_mode(
    base_env: dict[str, str], fake_bin: Path, tmp_path: Path
) -> None:
    workspace = tmp_path / "ws-native-storage"
    init_work_branch_workspace(workspace)
    cli_log = tmp_path / "codex-native-storage.log"
    model_cache = tmp_path / "shared" / "models"
    xdg_config_home = tmp_path / "xdg-config-native-storage"
    write_xdg_config(
        xdg_config_home,
        "AR_STORAGE_DIRS=(\n"
        f'    "MY_MODEL_CACHE={model_cache}"\n'
        ")\n",
    )
    make_executable(
        fake_bin / "codex",
        "#!/bin/sh\n"
        "printf '%s' \"${MY_MODEL_CACHE-}\" > \"${FAKE_CODEX_LOG:?}\"\n",
    )

    result = run(
        [
            str(AGENTIC_TEAM),
            "--sandbox", "none",
            "--cli", "codex",
            *at_launch_args(workspace),
        ],
        {
            **base_env,
            "XDG_CONFIG_HOME": str(xdg_config_home),
            "FAKE_CODEX_LOG": str(cli_log),
        },
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert model_cache.is_dir()
    assert cli_log.read_text() == str(model_cache)


def test_launcher_native_codex_yolo_uses_current_codex_flag(
    base_env: dict[str, str], fake_bin: Path, tmp_path: Path
) -> None:
    workspace = tmp_path / "ws-codex-yolo"
    init_work_branch_workspace(workspace)
    cli__log = tmp_path / "codex-yolo.log"
    make_executable(
        fake_bin / "codex",
        "#!/bin/sh\n"
        "printf 'args:%s\\n' \"$*\" >> \"${FAKE_CODEX_LOG:?}\"\n",
    )

    result = run(
        [
            str(AGENTIC_TEAM),
            "--sandbox",
            "none",
            "--cli",
            "codex",
            "--yolo",
            *at_launch_args(workspace),
        ],
        {**base_env, "FAKE_CODEX_LOG": str(cli__log)},
    )

    assert result.returncode == 0
    log_text = cli__log.read_text()
    assert "--dangerously-bypass-approvals-and-sandbox" in log_text
    assert "--full-auto" not in log_text


def test_launcher_uses_checkout_name_without_remote(
    base_env: dict[str, str], fake_bin: Path, tmp_path: Path
) -> None:
    workspace = tmp_path / "ws-without-remote"
    init_work_branch_workspace(workspace)
    make_executable(fake_bin / "codex", "#!/bin/sh\nexit 0\n")
    env = {**base_env}
    env["AR_CAPABILITIES"] = "agentic-notes"

    result = run(
        [
            str(AGENTIC_TEAM),
            "--sandbox", "none",
            "--cli",
            "codex",
            *at_launch_args(workspace),
        ],
        env,
    )

    assert result.returncode == 0
    assert (workspace.parent / "ws-without-remote-at" / "project-state").exists()

    remote = tmp_path / "different-remote-name.git"
    subprocess.run([REAL_GIT, "init", "--bare", str(remote)], check=True, capture_output=True, text=True)
    subprocess.run([REAL_GIT, "-C", str(workspace), "remote", "add", "origin", str(remote)], check=True)
    result = run(
        [
            str(AGENTIC_TEAM),
            "--sandbox", "none",
            "--cli",
            "codex",
            *at_launch_args(workspace, source_ref="kernel-search"),
        ],
        env,
    )

    assert result.returncode == 0
    assert (workspace.parent / "ws-without-remote-at" / "project-state").exists()


def test_launcher_uses_checkout_name_even_with_git_remote(
    base_env: dict[str, str], fake_bin: Path, tmp_path: Path
) -> None:
    workspace = tmp_path / "ws-remote-project"
    remote = tmp_path / "project.git"
    subprocess.run([REAL_GIT, "init", "--bare", str(remote)], check=True, capture_output=True, text=True)
    init_work_branch_workspace(workspace)
    subprocess.run([REAL_GIT, "-C", str(workspace), "remote", "add", "origin", str(remote)], check=True)
    make_executable(fake_bin / "codex", "#!/bin/sh\nexit 0\n")
    env = {**base_env}
    env["AR_CAPABILITIES"] = "agentic-notes"

    result = run(
        [
            str(AGENTIC_TEAM),
            "--sandbox", "none",
            "--cli",
            "codex",
            *at_launch_args(workspace),
        ],
        env,
    )

    assert result.returncode == 0
    assert (
        workspace.parent
        / "ws-remote-project-at"
        / "project-state"
        / "agent-notes"
        / "all-agents"
        / "always-injected.md"
    ).exists()
def test_launcher_preserves_at_workspace_root_from_code_symlink(
    base_env: dict[str, str], fake_bin: Path, tmp_path: Path
) -> None:
    workspace = tmp_path / "treeattention"
    init_work_branch_workspace(workspace)
    at_root = tmp_path / "custom-at"
    code_link = at_root / "kernel-search" / "code"
    code_link.parent.mkdir(parents=True)
    code_link.symlink_to(workspace, target_is_directory=True)
    make_executable(fake_bin / "codex", "#!/bin/sh\nexit 0\n")
    env = {**base_env}
    env["AR_CAPABILITIES"] = "agentic-notes"

    result = run(
        [
            str(AGENTIC_TEAM),
            "--sandbox",
            "none",
            "--cli",
            "codex",
            str(code_link),
        ],
        env,
    )

    assert result.returncode == 0
    assert (at_root / "project-state").exists()
    assert (at_root / "kernel-search" / "state").exists()
    assert not (tmp_path / "treeattention-at" / "project-state").exists()


def test_launcher_resume_followed_by_existing_directory_sets_workspace(
    base_env: dict[str, str], fake_bin: Path, tmp_path: Path
) -> None:
    workspace = tmp_path / "treeattention"
    init_work_branch_workspace(workspace)
    make_executable(fake_bin / "codex", "#!/bin/sh\nexit 0\n")

    result = run(
        [
            str(AGENTIC_TEAM),
            "--sandbox",
            "none",
            "--cli",
            "codex",
            "--debug-launch",
            *at_launch_args(workspace),
            "--resume",
        ],
        base_env,
    )

    assert result.returncode == 0
    assert f"Workspace:      {workspace}" in result.stdout
    cli_args_line = next(line for line in result.stdout.splitlines() if "CLI args:" in line)
    assert "mcp_servers.agentic_workflows.command=" in cli_args_line
    assert "mcp_servers.agentic_workflows.env_vars=" in cli_args_line
    assert '"AR_WORKFLOW_PATH"' in cli_args_line
    assert cli_args_line.endswith(" resume")


def test_launcher_codex_continue_translates_to_resume_last(
    base_env: dict[str, str], fake_bin: Path, tmp_path: Path
) -> None:
    workspace = tmp_path / "ws-codex-continue"
    init_work_branch_workspace(workspace)
    make_executable(fake_bin / "codex", "#!/bin/sh\nexit 0\n")

    result = run(
        [
            str(AGENTIC_TEAM),
            "--sandbox",
            "none",
            "--cli",
            "codex",
            "--debug-launch",
            "--continue",
            *at_launch_args(workspace),
        ],
        base_env,
    )

    assert result.returncode == 0
    cli_args_line = next(line for line in result.stdout.splitlines() if "CLI args:" in line)
    assert "mcp_servers.agentic_workflows.command=" in cli_args_line
    assert "mcp_servers.agentic_workflows.env_vars=" in cli_args_line
    assert '"AR_WORKFLOW_PATH"' in cli_args_line
    assert cli_args_line.endswith(" resume --last")


def test_launcher_preserves_existing_project_hooks_and_registers_global_hooks(
    base_env: dict[str, str], fake_bin: Path, tmp_path: Path
) -> None:
    workspace = tmp_path / "ws-existing-hooks"
    init_work_branch_workspace(workspace)
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
        str(AGENTIC_TEAM),
        "--sandbox", "none",
        "--cli",
        "codex",
        *at_launch_args(workspace),
    ]
    env = {**base_env}
    result = run(command, env)
    result_again = run(command, env)

    assert result.returncode == 0
    assert result_again.returncode == 0
    hooks = json.loads((workspace / ".codex" / "hooks.json").read_text())
    assert hooks["hooks"]["Stop"][0]["hooks"][0]["command"] == "printf existing"
    assert "PostCompact" not in hooks["hooks"]
    assert "PostToolUse" not in hooks["hooks"]
    global_hooks = json.loads((Path(env["HOME"]) / ".codex" / "hooks.json").read_text())
    assert len(global_hooks["hooks"]["PostCompact"]) == 1
    assert len(global_hooks["hooks"]["PostToolUse"]) == 1


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
    init_work_branch_workspace(workspace)
    make_executable(fake_bin / "codex", "#!/bin/sh\nexit 0\n")
    make_executable(fake_bin / "nvidia-smi", "#!/bin/sh\nexit 1\n")
    make_executable(fake_bin / "rocm-smi", "#!/bin/sh\necho 'ROCm GPU'; exit 0\n")

    result = run(
        [
            str(AGENTIC_TEAM),
            "--sandbox", "none",
            "--cli",
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
    init_work_branch_workspace(workspace)
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
            str(AGENTIC_TEAM),
            "--sandbox", "none",
            "--cli",
            "codex",
            "--capability",
            "cluster-run",
            *at_launch_args(workspace),
        ],
        base_env,
    )

    assert result.returncode == 0
    skill_path = workspace / ".agents" / "skills" / "cluster-run" / "SKILL.md"
    assert skill_path.exists()
    skill_text = skill_path.read_text()
    assert "Generated by agentic-team" in skill_text
    assert "cluster-run status" in skill_text
    instruction_text = (workspace / "AGENTS.md").read_text()
    assert "AGENTIC-TEAM-SKILL-INSTRUCTIONS-START cluster-run" not in instruction_text
    assert "Job Backend: cluster-run" in instruction_text
    assert (workspace / ".agents" / "skills" / "retro" / "SKILL.md").exists()
    finalizer_agent = workspace / ".codex" / "agents" / "research-finalizer.toml"
    assert finalizer_agent.exists()
    assert 'model_reasoning_effort = "low"' in finalizer_agent.read_text()
    assert "Call the `start_workflow` tool" in finalizer_agent.read_text()
    assert (
        "agentic_workflows.research.research_finalizer:ResearchFinalizer"
        in finalizer_agent.read_text()
    )


def test_gpu_backend_flag_is_removed(base_env: dict[str, str], tmp_path: Path) -> None:
    workspace = tmp_path / "ws-removed-gpu-backend"
    init_work_branch_workspace(workspace)

    result = run(
        [
            str(AGENTIC_TEAM),
            "--gpu-backend",
            "cluster-run",
            str(workspace),
        ],
        base_env,
    )

    assert result.returncode == 1
    assert "--gpu-backend has been removed" in result.stdout
    assert "--capability cluster-run" in result.stdout


def test_allow_shared_branch_flag_is_removed(base_env: dict[str, str], tmp_path: Path) -> None:
    workspace = tmp_path / "ws-removed-shared-branch"
    init_work_branch_workspace(workspace)

    result = run(
        [
            str(AGENTIC_TEAM),
            "--allow-shared-branch",
            str(workspace),
        ],
        base_env,
    )

    assert result.returncode == 1
    assert "--allow-shared-branch has been removed" in result.stdout
    assert "Launch a separate AT work entry instead" in result.stdout


def test_remote_run_capability_checks_its_own_sandbox_requirement(
    base_env: dict[str, str], tmp_path: Path
) -> None:
    workspace = tmp_path / "ws-remote-run-preflight"
    init_work_branch_workspace(workspace)

    result = run(
        [
            str(AGENTIC_TEAM),
            "--sandbox",
            "none",
            "--capability",
            "remote-run",
            *at_launch_args(workspace),
        ],
        {**base_env},
    )

    assert result.returncode == 1
    assert "remote-run capability requires --sandbox apptainer" in result.stderr


def test_native_capability_renders_skill_and_instruction_overlay(
    base_env: dict[str, str], fake_bin: Path, tmp_path: Path
) -> None:
    workspace = tmp_path / "ws-capability"
    init_work_branch_workspace(workspace)
    make_executable(fake_bin / "codex", "#!/bin/sh\nexit 0\n")
    make_executable(fake_bin / "cluster-run", "#!/bin/sh\n[ \"$1\" = --help ] && exit 0\nexit 0\n")

    result = run(
        [
            str(AGENTIC_TEAM),
            "--sandbox", "none",
            "--cli",
            "codex",
            "--capability",
            "cluster-run",
            *at_launch_args(workspace),
        ],
        {**base_env},
    )

    assert result.returncode == 0
    assert (workspace / ".agents" / "skills" / "cluster-run" / "SKILL.md").exists()
    instruction_text = (workspace / "AGENTS.md").read_text()
    assert "AGENTIC-TEAM-SKILL-INSTRUCTIONS-START cluster-run" not in instruction_text
    assert "The `cluster-run` capability is active" in instruction_text


def test_native_claude_cluster_run_backend_uses_claude_skills_dir(
    base_env: dict[str, str], fake_bin: Path, tmp_path: Path
) -> None:
    workspace = tmp_path / "ws-claude-cluster"
    init_work_branch_workspace(workspace)
    claude_log = tmp_path / "claude.log"
    make_executable(
        fake_bin / "claude",
        "#!/bin/sh\nprintf '%s\\n' \"$*\" > \"${FAKE_CLAUDE_LOG:?}\"\n",
    )
    make_executable(fake_bin / "cluster-run", "#!/bin/sh\n[ \"$1\" = --help ] && exit 0\nexit 0\n")

    result = run(
        [
            str(AGENTIC_TEAM),
            "--sandbox", "none",
            "--cli",
            "claude",
            "--capability",
            "cluster-run",
            *at_launch_args(workspace),
        ],
        {**base_env, "FAKE_CLAUDE_LOG": str(claude_log)},
    )

    assert result.returncode == 0
    assert (workspace / ".claude" / "skills" / "cluster-run" / "SKILL.md").exists()
    research_skill = workspace / ".claude" / "skills" / "do_research" / "SKILL.md"
    assert research_skill.exists()
    assert "## Callback-Managed Skill" in research_skill.read_text()
    claude_agent = workspace / ".claude" / "agents" / "research-finalizer.md"
    assert claude_agent.exists()
    assert "codex_reasoning_effort" not in claude_agent.read_text()
    assert "## Callback-Managed Imperative Workflow" in claude_agent.read_text()
    claude_args = claude_log.read_text()
    assert "--mcp-config" in claude_args
    assert "agentic_workflows" in claude_args
    assert "agentic-team-client" in claude_args
    assert "exec-workflow-mcp" in claude_args
    settings_path = client_dir(workspace, "claude") / "settings.json"
    assert f"--settings {settings_path}" in claude_args
    assert not (workspace / ".agents" / "hooks" / "agentic-team-compaction-refresh.py").exists()
    assert not (workspace / ".claude" / "hooks").exists()
    assert not (workspace / ".claude" / "settings.local.json").exists()
    claude_settings = json.loads(settings_path.read_text())
    claude_command = claude_settings["hooks"]["SessionStart"][0]["hooks"][0]["command"]
    assert claude_settings["hooks"]["SessionStart"][0]["matcher"] == "compact"
    assert "agentic-team-client" in claude_command
    assert "hook claude-compact --client claude" in claude_command


def test_native_gemini_cluster_run_backend_uses_gemini_skills_dir(
    base_env: dict[str, str], fake_bin: Path, tmp_path: Path
) -> None:
    workspace = tmp_path / "ws-gemini-cluster"
    init_work_branch_workspace(workspace)
    make_executable(fake_bin / "gemini", "#!/bin/sh\nexit 0\n")
    make_executable(fake_bin / "cluster-run", "#!/bin/sh\n[ \"$1\" = --help ] && exit 0\nexit 0\n")

    result = run(
        [
            str(AGENTIC_TEAM),
            "--sandbox", "none",
            "--cli",
            "gemini",
            "--capability",
            "cluster-run",
            *at_launch_args(workspace),
        ],
        base_env,
    )

    assert result.returncode == 0
    assert (workspace / ".gemini" / "skills" / "cluster-run" / "SKILL.md").exists()
    assert (workspace / ".gemini" / "skills" / "do_research" / "SKILL.md").exists()
    gemini_agent = workspace / ".gemini" / "agents" / "research-finalizer.md"
    assert gemini_agent.exists()
    assert "codex_reasoning_effort" not in gemini_agent.read_text()
    assert "## Callback-Managed Imperative Workflow" in gemini_agent.read_text()
    assert not (workspace / ".agents" / "skills" / "cluster-run" / "SKILL.md").exists()
    assert not (workspace / ".agents" / "hooks" / "agentic-team-compaction-refresh.py").exists()
    assert not (workspace / ".gemini" / "hooks").exists()
    assert not (workspace / ".gemini" / "settings.json").exists()
    settings_path = client_dir(workspace, "gemini") / "settings.json"
    gemini_settings = json.loads(settings_path.read_text())
    assert "agentic_tools" not in gemini_settings["mcpServers"]
    assert gemini_settings["mcpServers"]["agentic_workflows"]["command"].endswith("agentic-team-client")
    assert gemini_settings["mcpServers"]["agentic_workflows"]["args"] == [
        "exec-workflow-mcp", "--client", "gemini"
    ]
    precompress_command = gemini_settings["hooks"]["PreCompress"][0]["hooks"][0]["command"]
    before_model_commands = [
        hook["command"]
        for group in gemini_settings["hooks"]["BeforeModel"]
        for hook in group["hooks"]
    ]
    before_model_command = before_model_commands[0]
    assert "hook gemini-mark --client gemini" in precompress_command
    assert "hook gemini-inject --client gemini" in before_model_command
    assert any("hook gemini-steering --client gemini" in command for command in before_model_commands)


def test_native_opencode_cluster_run_backend_uses_opencode_skills_dir(
    base_env: dict[str, str], fake_bin: Path, tmp_path: Path
) -> None:
    workspace = tmp_path / "ws-opencode-cluster"
    init_work_branch_workspace(workspace)
    make_executable(fake_bin / "opencode", "#!/bin/sh\nexit 0\n")
    make_executable(fake_bin / "cluster-run", "#!/bin/sh\n[ \"$1\" = --help ] && exit 0\nexit 0\n")

    result = run(
        [
            str(AGENTIC_TEAM),
            "--sandbox", "none",
            "--cli",
            "opencode",
            "--capability",
            "cluster-run",
            *at_launch_args(workspace),
        ],
        base_env,
    )

    assert result.returncode == 0
    assert (workspace / ".opencode" / "skills" / "cluster-run" / "SKILL.md").exists()
    assert (workspace / ".opencode" / "skills" / "do_research" / "SKILL.md").exists()
    opencode_agent = workspace / ".opencode" / "agents" / "research-finalizer.md"
    assert opencode_agent.exists()
    opencode_agent_text = opencode_agent.read_text()
    assert "mode: subagent" in opencode_agent_text
    assert "codex_reasoning_effort" not in opencode_agent_text
    assert "## Callback-Managed Imperative Workflow" in opencode_agent_text
    assert not (workspace / ".agents" / "skills" / "cluster-run" / "SKILL.md").exists()
    opencode_plugin = client_dir(workspace, "opencode") / "plugins" / "agentic-team-compaction.ts"
    assert opencode_plugin.exists()
    opencode_plugin_text = opencode_plugin.read_text()
    assert "experimental.session.compacting" in opencode_plugin_text
    assert "You have just experienced context compaction" in opencode_plugin_text
    assert "since the last compaction" in opencode_plugin_text
    assert "execFileSync" in opencode_plugin_text
    assert "capability-refresh" in opencode_plugin_text
    assert str(workspace / "AGENTS.md") in opencode_plugin_text
    assert not (workspace / "opencode.json").exists()
    opencode_settings = json.loads((client_dir(workspace, "opencode") / "opencode.json").read_text())
    assert "agentic_tools" not in opencode_settings["mcp"]
    assert opencode_settings["mcp"]["agentic_workflows"]["command"][0].endswith(
        "/agentic-team-client"
    )
    assert opencode_settings["mcp"]["agentic_workflows"]["command"][1:] == [
        "exec-workflow-mcp", "--client", "opencode"
    ]


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
    config_text = (config_dir / "agentic-team" / "config.sh").read_text()
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
            "--cli",
            "codex",
            "--write-config",
            "--force",
        ],
        {**base_env, "XDG_CONFIG_HOME": str(config_dir)},
    )

    assert result.returncode == 0
    config_text = (config_dir / "agentic-team" / "config.sh").read_text()
    assert 'AR_SANDBOX="none"' in config_text
    assert 'AR_CAPABILITIES="agentic-notes,experiment-log"' in config_text
    assert 'AR_AUTO_BUILD="true"' in config_text
    assert (bin_dir / "agentic-team-client").is_symlink()
    assert read_log(base_env["FAKE_PODMAN_LOG"]) == ""
    assert read_log(base_env["FAKE_DOCKER_LOG"]) == ""


def test_prepare_codex_client_registers_context_without_launching_session(
    base_env: dict[str, str], fake_bin: Path, tmp_path: Path
) -> None:
    workspace = tmp_path / "ws-prepare-codex"
    init_work_branch_workspace(workspace)
    codex_log = tmp_path / "prepare-codex.log"
    make_executable(
        fake_bin / "codex",
        "#!/bin/sh\nprintf '%s\\n' \"$*\" >> \"${FAKE_CODEX_LOG:?}\"\n",
    )
    env = {**base_env, "FAKE_CODEX_LOG": str(codex_log)}

    result = run(
        [
            str(AGENTIC_TEAM),
            "--prepare-client",
            "--cli", "codex",
            *at_launch_args(workspace),
        ],
        env,
    )

    assert result.returncode == 0
    assert "Starting Codex CLI" not in result.stdout
    context_path = client_dir(workspace, "codex") / "context.json"
    launcher_path = client_dir(workspace, "codex") / "launch"
    assert f"Prepared codex client context: {context_path}" in result.stdout
    assert f"Client working directory: {workspace}" in result.stdout
    assert f":{workspace}" in next(
        line for line in result.stdout.splitlines() if line.startswith("SSH project location: ")
    )
    assert context_path.is_file()
    instruction_text = (workspace / "AGENTS.md").read_text()
    assert "## External Client Commands" in instruction_text
    assert "ordinary shell may not inherit Agentic Team's capability `PATH`" in instruction_text
    assert "`agentic-team-client exec --client codex -- COMMAND [ARGS...]`" in instruction_text
    assert "`branch-snapshot`:" not in instruction_text
    assert str(REPO_ROOT / "capabilities/branch/bin/branch-snapshot") not in instruction_text
    assert os.access(launcher_path, os.X_OK)
    launcher_text = launcher_path.read_text()
    assert "agentic-team-client exec" in launcher_text
    assert f"--manifest {context_path}" in launcher_text
    calls = codex_log.read_text().splitlines()
    assert calls[0] == "mcp remove agentic_workflows"
    assert calls[1].startswith("mcp add agentic_workflows -- ")
    assert "exec-workflow-mcp --client codex" in calls[1]


@pytest.mark.parametrize("client", ["claude", "gemini", "opencode", "pi"])
def test_prepared_client_launcher_restores_external_context(
    client: str, base_env: dict[str, str], fake_bin: Path, tmp_path: Path
) -> None:
    workspace = tmp_path / f"ws-prepare-{client}"
    init_work_branch_workspace(workspace)
    client_log = tmp_path / f"prepare-{client}.log"
    make_executable(
        fake_bin / client,
        "#!/bin/sh\n"
        "printf 'cwd:%s\\n' \"$PWD\" >> \"${FAKE_CLIENT_LOG:?}\"\n"
        "printf 'args:%s\\n' \"$*\" >> \"${FAKE_CLIENT_LOG:?}\"\n"
        "printf 'gemini:%s\\n' \"${GEMINI_CLI_SYSTEM_SETTINGS_PATH-}\" >> \"${FAKE_CLIENT_LOG:?}\"\n"
        "printf 'opencode:%s\\n' \"${OPENCODE_CONFIG-}\" >> \"${FAKE_CLIENT_LOG:?}\"\n",
    )
    env = {**base_env, "FAKE_CLIENT_LOG": str(client_log)}

    prepared = run(
        [
            str(AGENTIC_TEAM),
            "--prepare-client",
            "--cli", client,
            *at_launch_args(workspace),
        ],
        env,
    )
    assert prepared.returncode == 0, prepared.stderr
    external = client_dir(workspace, client)
    context = json.loads((external / "context.json").read_text())
    launched = subprocess.run(
        [str(external / "launch")],
        env=env,
        capture_output=True,
        text=True,
    )
    assert launched.returncode == 0, launched.stderr
    log = client_log.read_text()
    assert f"cwd:{workspace}" in log
    if client == "gemini":
        assert f"gemini:{external / 'settings.json'}" in log
        assert context["environment"]["GEMINI_CLI_SYSTEM_SETTINGS_PATH"] == str(
            external / "settings.json"
        )
    if client == "opencode":
        assert f"opencode:{external / 'opencode.json'}" in log
        assert context["environment"]["OPENCODE_CONFIG"] == str(
            external / "opencode.json"
        )


# ── pi (@earendil-works/pi-coding-agent) CLI-tool support ────────────────

def test_launcher_podman_runs_pi_cli_(base_env: dict[str, str], tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    init_work_branch_workspace(workspace)

    result = run(
        [str(AGENTIC_TEAM), "--sandbox", "podman", "--cli", "pi", *at_launch_args(workspace)],
        base_env,
    )

    assert result.returncode == 0
    assert "Starting pi" in result.stdout
    podman_log = read_log(base_env["FAKE_PODMAN_LOG"])
    assert "run --rm" in podman_log
    assert "SANDBOX_CLI=pi" in podman_log
    assert f"{REPO_ROOT}:/opt/agentic-team:ro" in podman_log
    assert "PATH=" in podman_log
    assert "/opt/agentic-team/scripts/bin" in podman_log
    assert "/opt/agentic-team/scripts/lib/commands" in podman_log
    # pi reads AGENTS.md; the launcher must seed it into the workspace.
    assert (workspace / "AGENTS.md").exists()
    # pi uses the shared agent-compatible project skill path.
    for skill in ("do_research", "retro"):
        assert (workspace / ".agents" / "skills" / skill / "SKILL.md").exists()
    assert not (workspace / ".agents" / "skills" / "experiment_log" / "SKILL.md").exists()
    pi_extension = client_dir(workspace, "pi") / "extensions" / "agentic-team-compaction.ts"
    assert pi_extension.exists()
    assert not (workspace / ".agents" / "hooks" / "agentic-team-compaction-refresh.py").exists()
    pi_extension_text = pi_extension.read_text()
    assert 'pi.on("session_compact"' in pi_extension_text
    assert "You have just experienced context compaction" in pi_extension_text
    assert "since the last compaction" in pi_extension_text
    assert "execFileSync" in pi_extension_text
    assert "capability-refresh" in pi_extension_text
    assert "/workspace/AGENTS.md" in pi_extension_text
    assert not (workspace / ".pi" / "mcp.json").exists()
    pi_mcp = json.loads((Path(base_env["HOME"]) / ".pi" / "agent" / "mcp.json").read_text())
    assert "agentic_tools" not in pi_mcp["mcpServers"]
    assert pi_mcp["mcpServers"]["agentic_workflows"]["command"] == "agentic-team-client"
    assert pi_mcp["mcpServers"]["agentic_workflows"]["args"] == [
        "exec-workflow-mcp", "--client", "pi"
    ]
    pi_research_skill = workspace / ".agents" / "skills" / "do_research" / "SKILL.md"
    assert "## Callback-Managed Skill" in pi_research_skill.read_text()
    assert "npm:pi-mcp-extension@1.5.0" in podman_log
    assert read_log(base_env["FAKE_DOCKER_LOG"]) == ""


def test_pi_translates_resume_to_session_and_warns_on_yolo(
    base_env: dict[str, str], tmp_path: Path
) -> None:
    workspace = tmp_path / "ws"
    init_work_branch_workspace(workspace)

    result = run(
        [
            str(AGENTIC_TEAM),
            "--sandbox", "podman",
            "--cli",
            "pi",
            "--debug-launch",
            "--resume",
            "ABC123",
            "--yolo",
            *at_launch_args(workspace),
        ],
        base_env,
    )

    assert result.returncode == 0
    # pi has no bare --resume ID; it maps to --session ID.
    assert "--session ABC123" in result.stdout
    # --debug-launch enables pi's verbose startup.
    assert "--verbose" in result.stdout
    assert "agentic-team-compaction.ts" in result.stdout
    assert "/client/pi/extensions/" in result.stdout
    assert "-e npm:pi-mcp-extension@1.5.0" in result.stdout
    # pi has no permission system, so --yolo is a no-op with a warning.
    assert "--yolo has no effect in pi mode" in result.stdout


def test_pi_apptainer_bind_and_config_store_wiring() -> None:
    launcher_text = AGENTIC_TEAM.read_text()
    pi_adapter = (CLI_ADAPTER_DIR / "pi.sh").read_text()
    # Apptainer path binds the host pi config dir (~/.pi) into the sandbox.
    assert 'BIND_ARGS+=(--bind "$PI_STATE_DIR:$AR_SANDBOX_HOME/.pi")' in pi_adapter
    assert 'PI_STATE_DIR="$HOME/.pi"' in pi_adapter
    # Docker/Podman path seeds the per-CLI-tool dir inside the single config store.
    assert '"$AR_CONFIG_STORE/.pi/agent"' in pi_adapter
    # pi uses AGENTS.md as its instruction file.
    assert 'printf \'%s\\n\' "AGENTS.md"' in pi_adapter
    # pi shares the generated project-skill setup.
    assert "setup_project_skills" in launcher_text


def test_launcher_has_no_legacy_slash_command_wiring() -> None:
    launcher_text = AGENTIC_TEAM.read_text()

    assert "SCRIPT_DIR/commands" not in launcher_text
    assert ".claude/commands" not in launcher_text
    assert "OPENCODE_COMMANDS_DIR" not in launcher_text
