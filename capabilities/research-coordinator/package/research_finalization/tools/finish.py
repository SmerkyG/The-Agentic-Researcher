"""Finish a research finalization and clean successful staging state."""

from __future__ import annotations

from typing import Literal

from agentic_tools import PythonTool

from research_finalization.records import FinalizationTicket
from research_finalization.tools._state import finish_ticket, load_ticket


class FinalizationFinishTool(PythonTool[FinalizationTicket]):
    """Persist terminal status and clean a successful temporary worktree."""

    root: str
    state: Literal["complete", "failed"]
    error: str | None = None

    def execute(self) -> FinalizationTicket:
        root, manifest = load_ticket(self.root)
        return finish_ticket(root, manifest, state=self.state, error=self.error)
