"""Public Research Finalizer contract."""

from __future__ import annotations

from typing import ClassVar

from agentic_workflows.contract import AgentWorkflow, WorkflowRecord
from agentic_workflows.research.agentic_notes import AgenticNotesUpdateTool
from agentic_workflows.research.experiment_log import ExperimentLogAppendTool
from agentic_workflows.research.git import Snapshot
from agentic_workflows.research.research_state import WorkStateSnapshot


class ResearchFinalizerResult(WorkflowRecord):
    errors: list[str]


class ResearchFinalizer(AgentWorkflow[ResearchFinalizerResult]):
    """Invocation contract for finalizing one research result."""

    agent_name: ClassVar[str] = "research-finalizer"
    experiment_log: ExperimentLogAppendTool | None = None
    note_update: AgenticNotesUpdateTool | None = None
    code_snapshot: Snapshot | None = None
    work_state_snapshot: WorkStateSnapshot
