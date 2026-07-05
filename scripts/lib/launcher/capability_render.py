#!/usr/bin/env -S uv run --script
# /// script
# dependencies = ["PyYAML>=6.0"]
# ///
"""Python capability renderer for Agentic Team.

Render paths are intentionally Python-only. Lifecycle hooks may still be
arbitrary executables, but rendered instruction content comes from a capability
`render.py` module so launcher rendering has one structured implementation.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, replace
import importlib.util
import os
from pathlib import Path
import re
import sys
from types import ModuleType
from typing import Any, Callable


REPO_ROOT = Path(__file__).resolve().parents[3]


class CapabilityRenderError(RuntimeError):
    pass


@dataclass(frozen=True)
class RenderContext:
    project_dir: Path
    agent_type: str
    work_branch: str
    cli: str
    repo_root: Path
    state_root: Path
    capability_name: str = ""
    capability_root: Path | None = None


def enabled_capability_names() -> list[str]:
    raw = os.environ.get("AR_CAPABILITIES", "agentic-notes,experiment-log")
    names: list[str] = []
    seen: set[str] = set()
    for name in raw.replace(",", " ").split():
        if not name or name == "none":
            continue
        if not re.match(r"^[A-Za-z0-9._-]+$", name):
            print(f"Warning: Ignoring invalid capability name: {name}", file=sys.stderr)
            continue
        if name not in seen:
            seen.add(name)
            names.append(name)
    return names


def capability_root(capability_name: str, state_root: Path) -> Path | None:
    candidates = [
        state_root / "repos" / "org-agentic-notes" / "capabilities" / capability_name,
        REPO_ROOT / "capabilities" / capability_name,
    ]
    for root in candidates:
        if root.is_dir():
            return root
    return None


def module_name_for(capability_name: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_]", "_", capability_name)
    return f"agentic_team_capability_render_{safe}"


def load_render_module(capability_name: str, root: Path) -> ModuleType | None:
    render_path = root / "render.py"
    if not render_path.is_file():
        return None
    spec = importlib.util.spec_from_file_location(module_name_for(capability_name), render_path)
    if spec is None or spec.loader is None:
        raise CapabilityRenderError(f"could not load render module for capability {capability_name}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    for path in (root / "lib", root):
        path_text = str(path)
        if path.exists() and path_text not in sys.path:
            sys.path.insert(0, path_text)
    spec.loader.exec_module(module)
    return module


def capability_context(base: RenderContext, capability_name: str) -> tuple[RenderContext, ModuleType | None]:
    root = capability_root(capability_name, base.state_root)
    if root is None:
        return replace(base, capability_name=capability_name, capability_root=None), None
    ctx = replace(base, capability_name=capability_name, capability_root=root)
    return ctx, load_render_module(capability_name, root)


def call_render_func(module: ModuleType, function_name: str, *args: Any) -> str:
    func = getattr(module, function_name, None)
    if func is None:
        return ""
    if not callable(func):
        raise CapabilityRenderError(f"{module.__file__}: {function_name} is not callable")
    value = func(*args)
    if value is None:
        return ""
    if not isinstance(value, str):
        raise CapabilityRenderError(f"{module.__file__}: {function_name} must return a string")
    return value.rstrip()


def render_instruction(args: argparse.Namespace, base: RenderContext) -> None:
    sections: list[str] = []
    for capability_name in enabled_capability_names():
        ctx, module = capability_context(base, capability_name)
        if module is None:
            continue
        section = call_render_func(module, "render_instruction", ctx)
        if section:
            sections.append(section)
    if sections:
        print("\n\n".join(sections).rstrip())
        print()


def render_agent_section(args: argparse.Namespace, base: RenderContext) -> None:
    ctx, module = capability_context(base, args.capability)
    if module is None:
        return
    section = call_render_func(module, "render_agent_section", ctx, args.section_agent_type)
    if section:
        print(section)


def render_agent_sections(args: argparse.Namespace, base: RenderContext) -> None:
    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    ctx, module = capability_context(base, args.capability)
    if module is None:
        return

    rendered: dict[str, str] = {}
    render_many = getattr(module, "render_agent_sections", None)
    if render_many is not None:
        if not callable(render_many):
            raise CapabilityRenderError(f"{module.__file__}: render_agent_sections is not callable")
        value = render_many(ctx, args.section_agent_type)
        if not isinstance(value, dict):
            raise CapabilityRenderError(f"{module.__file__}: render_agent_sections must return a dict")
        for agent_type, text in value.items():
            if not isinstance(agent_type, str) or not isinstance(text, str):
                raise CapabilityRenderError(
                    f"{module.__file__}: render_agent_sections must return dict[str, str]"
                )
            rendered[agent_type] = text.rstrip()
    else:
        for agent_type in args.section_agent_type:
            rendered[agent_type] = call_render_func(module, "render_agent_section", ctx, agent_type)

    for agent_type, text in rendered.items():
        if not re.match(r"^[A-Za-z0-9._-]+$", agent_type):
            raise CapabilityRenderError(f"invalid agent type: {agent_type}")
        (output_dir / f"{agent_type}.md").write_text(text.rstrip() + "\n", encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-dir", required=True)
    parser.add_argument("--agent-type", default=os.environ.get("AR_MAIN_AGENT", "research-coordinator"))
    parser.add_argument("--work-branch", default=os.environ.get("AR_WORK_BRANCH", ""))
    parser.add_argument("--cli", default=os.environ.get("AR_CLI", "codex"))
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("instruction")
    p.set_defaults(func=render_instruction)

    p = sub.add_parser("agent-section")
    p.add_argument("--capability", required=True)
    p.add_argument("--agent-type", dest="section_agent_type", required=True)
    p.set_defaults(func=render_agent_section)

    p = sub.add_parser("agent-sections")
    p.add_argument("--capability", required=True)
    p.add_argument("--output-dir", required=True)
    p.add_argument("--agent-type", dest="section_agent_type", action="append", required=True)
    p.set_defaults(func=render_agent_sections)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    base = RenderContext(
        project_dir=Path(args.project_dir).resolve(),
        agent_type=args.agent_type,
        work_branch=args.work_branch,
        cli=args.cli,
        repo_root=REPO_ROOT,
        state_root=Path(os.environ.get("AR_STATE_ROOT", "~/.cache/agentic-team")).expanduser(),
    )
    try:
        args.func(args, base)
    except CapabilityRenderError as exc:
        print(f"capability-render: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
