"""Public Research Coordinator contract."""

from __future__ import annotations

from typing import ClassVar

from agentic_workflows.contract import UserFacingWorkflow


class ResearchCoordinator(UserFacingWorkflow[None]):
    """Top-level workflow interface and do_research skill receiver."""

    agent_name: ClassVar[str] = "research-coordinator"
