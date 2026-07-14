"""Research report and work-state operation contracts."""

from __future__ import annotations

from typing import ClassVar

from agentic_workflows.contract import CommandResult, Value, WorkflowRecord, YAMLArgvTool


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


class ResearchStateInitializeTool(YAMLArgvTool[CommandResult]):
    """Initialize work-state records from an approved research plan."""

    argv_template: ClassVar[tuple[str, ...]] = ("research-coordinator-initialize-state",)
    plan: str = Value("Approved work-branch research plan")
