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
from functools import lru_cache
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
    capability_roots: tuple[Path, ...] = ()


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


def capability_root(capability_name: str, project_dir: Path, state_root: Path) -> Path | None:
    candidates = [
        project_dir / ".agentic-team" / "capabilities" / capability_name,
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


@lru_cache(maxsize=None)
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
    root = capability_root(capability_name, base.project_dir, base.state_root)
    if root is None:
        return replace(base, capability_name=capability_name, capability_root=None), None
    ctx = replace(base, capability_name=capability_name, capability_root=root)
    return ctx, load_render_module(capability_name, root)


def enabled_capability_roots(project_dir: Path, state_root: Path) -> tuple[Path, ...]:
    roots: list[Path] = []
    for capability_name in enabled_capability_names():
        root = capability_root(capability_name, project_dir, state_root)
        if root is not None:
            roots.append(root)
    return tuple(roots)


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


def bundle_output_path(output_dir: Path, relative_path: str) -> Path:
    path = (output_dir / relative_path).resolve()
    if path != output_dir and output_dir not in path.parents:
        raise CapabilityRenderError(f"bundle output escapes output directory: {relative_path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def write_bundle_text(output_dir: Path, relative_path: str, text: str) -> None:
    path = bundle_output_path(output_dir, relative_path)
    path.write_text(text.rstrip() + ("\n" if text else ""), encoding="utf-8")


def render_bundle(args: argparse.Namespace, base: RenderContext) -> None:
    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    for capability_name, source_kind, source_path, output_path in args.source_request:
        if source_kind not in {"agent", "skill"}:
            raise CapabilityRenderError(f"invalid source kind: {source_kind}")
        ctx, module = capability_context(base, capability_name)
        if module is None:
            raise CapabilityRenderError(f"source renderer capability not found: {capability_name}")
        source = Path(source_path).resolve()
        rendered = call_render_func(module, "render_source", ctx, source, source_kind)
        if not rendered:
            raise CapabilityRenderError(
                f"{module.__file__}: render_source returned no content for {source}"
            )
        write_bundle_text(output_dir, output_path, rendered)

    section_requests: dict[str, list[tuple[str, str]]] = {}
    for capability_name, agent_type, output_path in args.agent_section_request:
        section_requests.setdefault(capability_name, []).append((agent_type, output_path))

    for capability_name, requests in section_requests.items():
        ctx, module = capability_context(base, capability_name)
        if module is None:
            continue
        render_many = getattr(module, "render_agent_sections", None)
        if render_many is not None:
            if not callable(render_many):
                raise CapabilityRenderError(
                    f"{module.__file__}: render_agent_sections is not callable"
                )
            rendered = render_many(ctx, [agent_type for agent_type, _output in requests])
            if not isinstance(rendered, dict):
                raise CapabilityRenderError(
                    f"{module.__file__}: render_agent_sections must return a dict"
                )
            for agent_type, output_path in requests:
                text = rendered.get(agent_type, "")
                if not isinstance(text, str):
                    raise CapabilityRenderError(
                        f"{module.__file__}: render_agent_sections must return dict[str, str]"
                    )
                write_bundle_text(output_dir, output_path, text)
        else:
            for agent_type, output_path in requests:
                text = call_render_func(module, "render_agent_section", ctx, agent_type)
                write_bundle_text(output_dir, output_path, text)

    instruction_sections: list[str] = []
    for capability_name in enabled_capability_names():
        ctx, module = capability_context(base, capability_name)
        if module is None:
            continue
        section = call_render_func(module, "render_instruction", ctx)
        if section:
            instruction_sections.append(section)
    write_bundle_text(
        output_dir,
        "instructions.md",
        "\n\n".join(instruction_sections).rstrip(),
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-dir", required=True)
    parser.add_argument("--agent-type", default=os.environ.get("AR_MAIN_AGENT"))
    parser.add_argument("--work-branch", default=os.environ.get("AR_WORK_BRANCH", ""))
    parser.add_argument("--cli", default=os.environ.get("AR_CLI", "codex"))
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("bundle")
    p.add_argument("--output-dir", required=True)
    p.add_argument(
        "--source",
        dest="source_request",
        action="append",
        nargs=4,
        default=[],
        metavar=("CAPABILITY", "KIND", "SOURCE", "OUTPUT"),
    )
    p.add_argument(
        "--agent-section",
        dest="agent_section_request",
        action="append",
        nargs=3,
        default=[],
        metavar=("CAPABILITY", "AGENT_TYPE", "OUTPUT"),
    )
    p.set_defaults(func=render_bundle)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.agent_type:
        parser.error("--agent-type or AR_MAIN_AGENT is required")
    project_dir = Path(args.project_dir).resolve()
    state_root = Path(os.environ.get("AR_STATE_ROOT", "~/.cache/agentic-team")).expanduser()
    base = RenderContext(
        project_dir=project_dir,
        agent_type=args.agent_type,
        work_branch=args.work_branch,
        cli=args.cli,
        repo_root=REPO_ROOT,
        state_root=state_root,
        capability_roots=enabled_capability_roots(project_dir, state_root),
    )
    try:
        args.func(args, base)
    except CapabilityRenderError as exc:
        print(f"capability-render: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
