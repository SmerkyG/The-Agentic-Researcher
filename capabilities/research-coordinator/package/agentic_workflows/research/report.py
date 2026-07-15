"""Research report operation contracts."""

from __future__ import annotations

from typing import ClassVar

from agentic_workflows.contract import WorkflowRecord, YAMLArgvTool


class ReportAppendResult(WorkflowRecord):
    page: str
    page_number: int
    created: bool
    previous_lines: int
    lines: int


class ReportAppendTool(YAMLArgvTool[ReportAppendResult]):
    argv_template: ClassVar[tuple[str, ...]] = ("research-coordinator-report-append",)
    content: str
    work_state_dir: str | None = None
    max_lines: int = 300
