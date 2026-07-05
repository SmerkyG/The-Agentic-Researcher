"""Render experiment-log instruction content."""

from __future__ import annotations

from typing import Any


def render_instruction(ctx: Any) -> str:
    work_branch = ctx.work_branch
    if not work_branch:
        return ""
    return "\n".join(
        [
            "## Experiment Log",
            "",
            f"When this workflow records experiments, the active work-branch experiment log lives on the project work state branch `agentic/work-state/{work_branch}` at `experiment-log/`. The log is capability-owned and may not exist until the first experiment is recorded. Use the `experiment-logger` subagent for new experiment results and the `experiment-corrector` subagent for corrections. Within this work-branch log, experiment IDs are local, such as `E0001_block-sparse-baseline`; from other work-branch logs, refer to them as `{work_branch}::E0001_block-sparse-baseline`.",
            "",
            "Read the active work-branch experiment summary, when it exists, with:",
            "",
            "```bash",
            f"experiment-log summary --project-dir . --work-branch {work_branch}",
            "```",
        ]
    )
