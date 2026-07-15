"""Research work-state initialization operation contract."""

from __future__ import annotations

from typing import ClassVar

from agentic_workflows.contract import CommandResult, Value, YAMLArgvTool


class ResearchStateInitializeTool(YAMLArgvTool[CommandResult]):
    """Initialize work-state records from an approved research plan."""

    argv_template: ClassVar[tuple[str, ...]] = ("research-coordinator-initialize-state",)
    plan: str = Value("Approved work-branch research plan")
