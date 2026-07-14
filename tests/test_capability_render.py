from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
CAPABILITY_RENDER = REPO_ROOT / "scripts" / "lib" / "launcher" / "capability_render.py"
CAPABILITIES_SH = REPO_ROOT / "scripts" / "lib" / "launcher" / "capabilities.sh"


def test_launcher_batches_capability_rendering_into_one_callsite() -> None:
    launcher = CAPABILITIES_SH.read_text(encoding="utf-8")

    assert launcher.count("capability_render_command") == 2
    assert 'render_args=(bundle --output-dir "$CAPABILITY_RENDER_DIR")' in launcher
    assert "capability_render_command source" not in launcher
    assert "capability_render_command instruction" not in launcher
    assert "capability_render_command agent-section" not in launcher


def test_bundle_uses_capability_owned_render_functions(tmp_path: Path) -> None:
    project = tmp_path / "project"
    capability = project / ".agentic-team" / "capabilities" / "demo"
    capability.mkdir(parents=True)
    (capability / "render.py").write_text(
        "def render_source(ctx, source_path, source_kind):\n"
        "    return f'source:{source_kind}:{source_path.name}'\n\n"
        "def render_agent_sections(ctx, agent_types):\n"
        "    return {name: f'section:{name}' for name in agent_types}\n\n"
        "def render_instruction(ctx):\n"
        "    return 'instruction:demo'\n",
        encoding="utf-8",
    )
    first = tmp_path / "first.md"
    second = tmp_path / "second.md"
    first.write_text("first", encoding="utf-8")
    second.write_text("second", encoding="utf-8")
    output = tmp_path / "rendered"
    env = {
        **os.environ,
        "AR_CAPABILITIES": "demo",
        "AR_STATE_ROOT": str(tmp_path / "state"),
    }

    subprocess.run(
        [
            sys.executable,
            str(CAPABILITY_RENDER),
            "--project-dir",
            str(project),
            "--agent-type",
            "demo-main",
            "--work-branch",
            "demo-work",
            "--cli",
            "codex",
            "bundle",
            "--output-dir",
            str(output),
            "--source",
            "demo",
            "agent",
            str(first),
            "sources/first.md",
            "--source",
            "demo",
            "skill",
            str(second),
            "sources/second.md",
            "--agent-section",
            "demo",
            "helper",
            "sections/helper.md",
        ],
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )

    assert (output / "sources" / "first.md").read_text() == "source:agent:first.md\n"
    assert (output / "sources" / "second.md").read_text() == "source:skill:second.md\n"
    assert (output / "sections" / "helper.md").read_text() == "section:helper\n"
    assert (output / "instructions.md").read_text() == "instruction:demo\n"
