"""Read durable finalization status."""

from __future__ import annotations

from agentic_tools import PythonTool

from research_finalization.records import FinalizationStatusResult
from research_finalization.tools._state import load_ticket, safe_load_yaml, status_path


class FinalizationStatusTool(PythonTool[FinalizationStatusResult]):
    """Read durable finalization status without inspecting a child agent."""

    root: str

    def execute(self) -> FinalizationStatusResult:
        root, manifest = load_ticket(self.root)
        status = safe_load_yaml(status_path(root))
        return FinalizationStatusResult(
            id=str(manifest["id"]),
            root=str(root),
            status_path=str(status_path(root)),
            code_branch=str(manifest["code_branch"]),
            code_commit=str(manifest["code_commit"]),
            records_branch=str(manifest["records_branch"]),
            state=str(status.get("state") or "captured"),
            sequence=int(status["sequence"]) if status.get("sequence") is not None else None,
            created_at=status.get("created_at"),
            updated_at=status.get("updated_at"),
            active_at=status.get("active_at"),
            finished_at=status.get("finished_at"),
            failed_at=status.get("failed_at"),
            records_commit=status.get("records_commit"),
            records_changed=status.get("records_changed"),
            error=status.get("error"),
        )
