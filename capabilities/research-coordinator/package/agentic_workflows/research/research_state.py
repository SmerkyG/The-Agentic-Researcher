"""Native research work-state initialization operation."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess

from agentic_tools import PythonTool, Record, Value


class ResearchStateInitializeResult(Record):
    """Committed files created while initializing one research branch."""

    commit: str
    created: list[str]


def _run_git(
    repository: Path,
    *arguments: str,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        ["git", *arguments],
        cwd=repository,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if check and result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise RuntimeError(f"git {' '.join(arguments)} failed: {detail}")
    return result


def _write_if_missing(path: Path, content: str) -> bool:
    if path.exists():
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content.rstrip() + "\n", encoding="utf-8")
    return True


class ResearchStateInitializeTool(PythonTool[ResearchStateInitializeResult]):
    """Initialize work-state records from an approved research plan."""

    plan: str = Value("Approved work-branch research plan")
    work_state_dir: str | None = Value(
        "Explicit work-state directory, or null to use AR_WORK_STATE_DIR",
        default=None,
    )
    agent_name: str | None = Value(
        "Agent name owning the plan, or null to use AR_MAIN_AGENT",
        default=None,
    )
    work_branch: str | None = Value(
        "Research work branch, or null to use AR_WORK_BRANCH",
        default=None,
    )

    def execute(self) -> ResearchStateInitializeResult:
        plan = self.plan.strip()
        if not plan:
            raise ValueError("plan must be a non-empty string")

        state_value = self.work_state_dir or os.environ.get("AR_WORK_STATE_DIR")
        if not state_value:
            raise ValueError("work_state_dir or AR_WORK_STATE_DIR is required")
        state = Path(state_value).expanduser().resolve()
        if not (state / ".git").exists():
            raise ValueError(f"work-state directory is not a Git worktree: {state}")

        remote = _run_git(state, "remote", "get-url", "origin", check=False)
        if remote.returncode == 0 and remote.stdout.strip():
            _run_git(state, "pull", "--ff-only")

        agent_name = (
            self.agent_name
            or os.environ.get("AR_MAIN_AGENT")
            or "research-coordinator"
        )
        work_branch = (
            self.work_branch
            or os.environ.get("AR_WORK_BRANCH")
            or "research"
        )
        plan_path = state / "agent-notes" / agent_name / "always-injected.md"
        if plan_path.exists() and plan_path.read_text(encoding="utf-8").strip():
            raise ValueError(f"research state is already initialized: {plan_path}")

        plan_path.parent.mkdir(parents=True, exist_ok=True)
        plan_path.write_text(plan + "\n", encoding="utf-8")
        created = [plan_path.relative_to(state).as_posix()]
        if _write_if_missing(
            state / "condensed_report.md",
            f"# Condensed Report: {work_branch}\n\nNo completed findings yet.",
        ):
            created.append("condensed_report.md")
        if _write_if_missing(
            state / "report_page1.md",
            f"# Research Log: {work_branch}\n\n"
            "Research initialized; append completed analysis sections here.",
        ):
            created.append("report_page1.md")
        if _write_if_missing(
            state / "TODO.md",
            "# TODO\n\n- [ ] Run baseline evaluation",
        ):
            created.append("TODO.md")
        (state / "images").mkdir(exist_ok=True)

        _run_git(state, "add", "--", *created)
        staged = _run_git(state, "diff", "--cached", "--quiet", check=False)
        if staged.returncode not in {0, 1}:
            detail = (staged.stderr or staged.stdout).strip()
            raise RuntimeError(f"git diff --cached --quiet failed: {detail}")

        if staged.returncode == 1:
            _run_git(
                state,
                "commit",
                "-m",
                f"work-state: initialize {work_branch} research",
            )
            if remote.returncode == 0 and remote.stdout.strip():
                branch = _run_git(state, "branch", "--show-current").stdout.strip()
                _run_git(state, "push", "-u", "origin", branch)

        commit = _run_git(state, "rev-parse", "HEAD").stdout.strip()
        return ResearchStateInitializeResult(commit=commit, created=created)
