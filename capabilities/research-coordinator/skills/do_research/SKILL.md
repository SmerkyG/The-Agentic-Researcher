---
name: do_research
description: Set up or resume a research work branch in this workspace.
renderer: imperative-workflows
workflow_module: agentic_workflows.research.do_research
workflow_entry: do_research
workflow_receiver: agentic_workflows.research.research_coordinator:ResearchCoordinator
---

# Start Research

This skill is read only when invoked. Its workflow extends the current research
coordinator instead of launching another agent.

```python agentic-workflow
from __future__ import annotations

from agentic_workflows.research.research_coordinator import ResearchCoordinator
from agentic_workflows.research.research_state import ResearchStateInitializeTool


def do_research(self: ResearchCoordinator) -> None:
    """Initialize missing research state, then enter the coordinator workflow."""

    if self.evaluate("the active work branch has no initialized research plan"):
        goal: str = self.ask_user("Ask for the research goal and current codebase state.")
        metric: str = self.ask_user("Ask for the primary metric, direction, baseline, and evaluation command.")
        constraints: str = self.ask_user("Ask for fixed constraints, decision scale, off-limits areas, and compute budget.")
        plan: str = self.evaluate("complete research plan derived from goal, metric, and constraints")
        while True:
            review: str = self.ask_user(
                "Show the complete plan and ask for approval or requested changes."
            )
            if self.evaluate("the user approved the displayed plan without further changes"):
                break
            revised_plan: str = self.evaluate(
                "revised complete research plan incorporating the user's requested changes",
                guidance="The current plan and review response remain in scope.",
            )
            plan = revised_plan
        ResearchStateInitializeTool(plan=plan).run()

    self.on_startup()
    self.workflow()
```
