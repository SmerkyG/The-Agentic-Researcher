"""Public Research Finalizer contract."""

from __future__ import annotations

from typing import ClassVar

from agentic_workflows.contract import SubagentWorkflow, WorkflowRecord
from agentic_workflows.research.finalization import FinalizationTicket


class ResearchFinalizerResult(WorkflowRecord):
    errors: list[str]


class ResearchFinalizer(SubagentWorkflow[ResearchFinalizerResult]):
    """Invocation contract for finalizing one research result."""

    agent_name: ClassVar[str] = "research-finalizer"
    ticket: FinalizationTicket
