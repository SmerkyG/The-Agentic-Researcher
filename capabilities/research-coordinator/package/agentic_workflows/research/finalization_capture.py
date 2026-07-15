"""Coordinator-side research finalization capture operation."""

from __future__ import annotations

from typing import ClassVar

from agentic_workflows.contract import Value, YAMLArgvTool
from agentic_workflows.research.finalization import FinalizationTicket


class FinalizationCaptureTool(YAMLArgvTool[FinalizationTicket]):
    """Record the current code commit and freeze explicit report assets."""

    argv_template: ClassVar[tuple[str, ...]] = ("research-coordinator-finalization", "capture")

    report_assets: list[str] = Value(
        "Explicit report-asset file paths relative to the work-state directory",
        default_factory=list,
    )
    project_dir: str = "."
    work_state_dir: str | None = None
