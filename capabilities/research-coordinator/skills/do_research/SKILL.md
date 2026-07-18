---
name: do_research
description: Set up or resume a research work branch in this workspace.
renderer: imperative-workflows
workflow: agentic_workflows.research.do_research:do_research
workflow_receiver: agentic_workflows.research.research_coordinator:ResearchCoordinator
---

# Start Research

This skill is read only when invoked. Its workflow extends the current research
coordinator instead of launching another agent.
