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
            f"When a workflow records experiments, the active branch experiment log lives on records branch `agentic/branch-records/{work_branch}` at `experiment-log/`. The log is capability-owned and may not exist until the first experiment is recorded. Workflow code uses the native append and correction tools; outside that workflow, use `experiment-log summary` for inspection and do not rewrite experiment records manually. Within this branch log, experiment IDs are local, such as `E0001_block-sparse-baseline`; from other branch logs, refer to them as `{work_branch}::E0001_block-sparse-baseline`.",
            "",
            "Read the active work-branch experiment summary, when it exists, with:",
            "",
            "```bash",
            f"experiment-log summary --project-dir . --work-branch {work_branch}",
            "```",
        ]
    )
