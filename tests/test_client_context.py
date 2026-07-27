import json
import os
from pathlib import Path
import subprocess


REPO_ROOT = Path(__file__).resolve().parents[1]
CLIENT = REPO_ROOT / "scripts" / "bin" / "agentic-team-client"


def test_register_resolve_and_execute_context(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    nested = project / "nested"
    nested.mkdir()
    external = tmp_path / "at" / "work" / "client" / "codex"
    manifest = external / "context.json"
    registry = tmp_path / "config" / "client-contexts.json"
    env_file = tmp_path / "environment"
    env_file.write_text("AR_WORK_BRANCH=work\nVISIBLE_FROM_CONTEXT=yes\n")

    registered = subprocess.run(
        [
            str(CLIENT), "register",
            "--manifest", str(manifest),
            "--registry", str(registry),
            "--env-file", str(env_file),
            "--client", "codex",
            "--project-dir", str(project),
            "--instruction-path", str(project / "AGENTS.md"),
            "--main-agent", "general",
            "--work-branch", "work",
            "--work-name", "work",
            "--capabilities", "agentic-notes,imperative-workflows",
            "--workflow-mcp", "/bin/true",
            "--capability-refresh", "/bin/true",
        ],
        capture_output=True,
        text=True,
    )
    assert registered.returncode == 0, registered.stderr
    assert manifest.is_file()
    assert registry.is_file()
    context = json.loads(manifest.read_text())
    assert context["capabilities"] == ["agentic-notes", "imperative-workflows"]

    executed = subprocess.run(
        [
            str(CLIENT), "exec",
            "--client", "codex",
            "--registry", str(registry),
            "--cwd", str(nested),
            "--", "/bin/sh", "-c", "printf '%s:%s' \"$PWD\" \"$VISIBLE_FROM_CONTEXT\"",
        ],
        capture_output=True,
        text=True,
        env={**os.environ, "AR_CLIENT_CONTEXT": ""},
    )
    assert executed.returncode == 0, executed.stderr
    assert executed.stdout == f"{project}:yes"


def test_hook_is_a_noop_outside_registered_projects(tmp_path: Path) -> None:
    result = subprocess.run(
        [
            str(CLIENT), "hook", "codex-post-compact",
            "--client", "codex",
            "--registry", str(tmp_path / "missing.json"),
        ],
        input=json.dumps({"cwd": str(tmp_path)}),
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert json.loads(result.stdout) == {}
