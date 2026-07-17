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
def do_research(self: ResearchCoordinator) -> None:
    """Enter the coordinator, which initializes missing state before research."""

    self.on_startup()
    self.workflow()
```
