"""Structured MCP transport for persistent imperative agent workflows."""

from __future__ import annotations

import asyncio
import time
from typing import Any, Callable

from mcp.server.fastmcp import Context, FastMCP

from agentic_workflows import callback_runner


SERVER_INSTRUCTIONS = """Use these tools only for callback-managed imperative workflows.
Call start_workflow once after the user's first request, then process each returned event
and call resume_workflow with the exact run_id, boundary_id, and event-specific payload.
After context compaction, call reset_workflow_context once for the active run before resuming.
Never replace a structured tool call with an interactive shell callback."""


mcp = FastMCP(
    "agentic-workflows",
    instructions=SERVER_INSTRUCTIONS,
    log_level="WARNING",
)


def _transport_event(event: dict[str, object]) -> dict[str, Any]:
    """Replace CLI-specific resume instructions with structured MCP arguments."""

    result: dict[str, Any] = dict(event)
    boundary_id = result.get("boundary_id")
    run_id = result.get("run_id")
    result.pop("resume", None)
    if isinstance(boundary_id, str) and isinstance(run_id, str):
        result["resume"] = {
            "tool": "resume_workflow",
            "run_id": run_id,
            "boundary_id": boundary_id,
            "payload": "one JSON object appropriate for the event status",
        }
    return result


async def _run_blocking(
    action: Callable[[], dict[str, object]],
    *,
    context: Context,
    label: str,
) -> dict[str, Any]:
    """Run a blocking worker exchange while emitting periodic MCP progress."""

    started = time.monotonic()
    task = asyncio.create_task(asyncio.to_thread(action))
    while True:
        done, _pending = await asyncio.wait({task}, timeout=2.0)
        if done:
            return _transport_event(task.result())
        elapsed = time.monotonic() - started
        await context.report_progress(
            progress=elapsed,
            message=f"{label}; worker is executing Python or tool operations ({elapsed:.0f}s)",
        )


@mcp.tool()
async def start_workflow(
    implementation: str,
    inputs: dict[str, Any],
    context: Context,
) -> dict[str, Any]:
    """Start one persistent workflow after the user or parent request has arrived."""

    return await _run_blocking(
        lambda: callback_runner.start(implementation, inputs),
        context=context,
        label="Starting callback-managed workflow",
    )


@mcp.tool()
async def resume_workflow(
    run_id: str,
    boundary_id: str,
    payload: dict[str, Any],
    context: Context,
) -> dict[str, Any]:
    """Resume exactly one pending workflow boundary with a structured payload."""

    return await _run_blocking(
        lambda: callback_runner.resume(run_id, boundary_id, payload),
        context=context,
        label=f"Resuming workflow {run_id} at boundary {boundary_id}",
    )


@mcp.tool()
def workflow_status(run_id: str) -> dict[str, Any]:
    """Inspect durable state and recover the pending event after interruption."""

    result: dict[str, Any] = dict(callback_runner.status(run_id))
    pending_event = result.get("pending_event")
    if isinstance(pending_event, dict):
        result["pending_event"] = _transport_event(pending_event)
    return result


@mcp.tool()
async def cancel_workflow(
    run_id: str,
    context: Context,
) -> dict[str, Any]:
    """Cancel a callback-managed workflow and stop its persistent worker."""

    return await _run_blocking(
        lambda: callback_runner.cancel(run_id),
        context=context,
        label=f"Cancelling workflow {run_id}",
    )


@mcp.tool()
async def reset_workflow_context(
    run_id: str,
    context: Context,
) -> dict[str, Any]:
    """After context compaction, resend the pending boundary's cached definitions."""

    return await _run_blocking(
        lambda: callback_runner.reset_context(run_id),
        context=context,
        label=f"Resetting retained-context cache for workflow {run_id}",
    )


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
