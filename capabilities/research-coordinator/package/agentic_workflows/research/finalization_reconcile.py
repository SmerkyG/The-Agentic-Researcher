"""Coordinator-side reconciliation for interrupted finalization tickets."""

from __future__ import annotations

from typing import ClassVar

from agentic_workflows.contract import YAMLArgvTool
from agentic_workflows.research.finalization import FinalizationReconcileResult


class FinalizationReconcileTool(YAMLArgvTool[FinalizationReconcileResult]):
    """Repair safely recognizable interrupted finalizations at startup."""

    argv_template: ClassVar[tuple[str, ...]] = (
        "research-coordinator-finalization",
        "reconcile",
    )

    project_dir: str = "."
    work_branch: str | None = None
