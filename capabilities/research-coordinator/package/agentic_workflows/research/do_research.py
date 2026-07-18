"""Entry function for activating the research coordinator through a skill."""

from __future__ import annotations

from agentic_workflows.research.research_coordinator import ResearchCoordinator


def do_research(self: ResearchCoordinator) -> None:
    """Initialize the active state and enter the coordinator workflow."""

    self.on_startup()
    self.workflow()
