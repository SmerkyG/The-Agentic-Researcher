"""Render agent and skill sources that use imperative Python workflows."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from workflow_source import WorkflowRenderer


_RENDERERS: dict[tuple[Path, ...], WorkflowRenderer] = {}


def render_source(ctx: Any, source_path: Path, source_kind: str) -> str:
    package_roots = tuple(
        root / "package"
        for root in ctx.capability_roots
        if (root / "package").is_dir()
    )
    renderer = _RENDERERS.get(package_roots)
    if renderer is None:
        renderer = WorkflowRenderer(package_roots)
        _RENDERERS[package_roots] = renderer
    if source_kind == "agent":
        return renderer.render_callback(source_path)
    if source_kind == "skill":
        return renderer.render_callback_skill(source_path)
    return renderer.render(source_path)
