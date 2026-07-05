"""Render Agentic Notes instruction content."""

from __future__ import annotations

from contextlib import ExitStack
from pathlib import Path
import runpy
from types import SimpleNamespace
from typing import Any


_INTERNAL: dict[str, Any] | None = None


def internal() -> dict[str, Any]:
    global _INTERNAL
    if _INTERNAL is None:
        _INTERNAL = runpy.run_path(str(Path(__file__).resolve().parent / "lib" / "agentic-notes-internal"))
    return _INTERNAL


def with_render_locks(ctx: Any, command: str, agent_types: list[str], render: Any) -> Any:
    api = internal()
    args = SimpleNamespace(
        command=command,
        project_dir=str(ctx.project_dir),
        agent_type=agent_types,
        dynamic_only=False,
    )
    with ExitStack() as stack:
        for lock_path in api["lock_paths_for_args"](args):
            stack.enter_context(api["state_lock"](lock_path))
        return render()


def build_section(ctx: Any, agent_type: str, *, include_guidance: bool) -> str:
    api = internal()
    return api["build_notes_section"](
        ctx.project_dir,
        api["agent_type"](agent_type),
        include_guidance=include_guidance,
    ).rstrip()


def render_instruction(ctx: Any) -> str:
    module_path = Path(ctx.capability_root) / "instruction-modules" / "agentic-notes.md"

    def render() -> str:
        parts: list[str] = []
        if module_path.is_file():
            parts.append(module_path.read_text(encoding="utf-8").rstrip())
        dynamic = build_section(ctx, ctx.agent_type, include_guidance=False)
        if dynamic:
            parts.append(dynamic)
        return "\n\n".join(part for part in parts if part).rstrip()

    return with_render_locks(ctx, "render-section", [ctx.agent_type], render)


def render_agent_section(ctx: Any, agent_type: str) -> str:
    return with_render_locks(
        ctx,
        "render-section",
        [agent_type],
        lambda: build_section(ctx, agent_type, include_guidance=True),
    )


def render_agent_sections(ctx: Any, agent_types: list[str]) -> dict[str, str]:
    api = internal()

    def render() -> dict[str, str]:
        rendered: dict[str, str] = {}
        seen: set[str] = set()
        for raw_agent_type in agent_types:
            active_agent_type = api["agent_type"](raw_agent_type)
            if active_agent_type in seen:
                continue
            seen.add(active_agent_type)
            rendered[active_agent_type] = build_section(ctx, active_agent_type, include_guidance=True)
        return rendered

    return with_render_locks(ctx, "render-sections", agent_types, render)
