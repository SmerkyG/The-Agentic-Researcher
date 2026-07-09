"""Runtime contract for imperative Agentic Team workflow prototypes."""

from __future__ import annotations

from dataclasses import MISSING, dataclass, field
from typing import Any, Sequence


def Value(description: str, *, default: object = MISSING, default_factory: object = MISSING) -> object:
    """
    Describe one dataclass field that a non-mutating workflow evaluation fills.

    The Python annotation supplies the field type. The Value description supplies
    the model-facing field contract. When neither default nor default_factory is
    provided, the field remains required.
    """
    kwargs: dict[str, object] = {"metadata": {"description": description}}
    if default is not MISSING:
        kwargs["default"] = default
    if default_factory is not MISSING:
        kwargs["default_factory"] = default_factory
    return field(**kwargs)


@dataclass
class CommandResult:
    """Normalized result from a command-like registered tool."""

    returncode: int
    stdout: str = ""
    stderr: str = ""


class WorkflowBlocked(Exception):
    """The workflow cannot proceed without an external state change."""


class NeedsUser(WorkflowBlocked):
    """The workflow cannot proceed without user input."""


class WorkflowFailed(Exception):
    """The workflow failed and should not be resumed blindly."""


class SubagentUnavailable(WorkflowBlocked):
    """A required subagent could not be launched after retry."""


class AgentWorkflow:
    async def __call__(self) -> Any:
        """
        Run the workflow object's declared entrypoint.

        Subclasses override this with explicit typed positional-or-keyword
        parameters. They must not use keyword-only markers, *args, or **kwargs.
        """
        raise NotImplementedError

    def do(self, actions: Sequence[str], **kwargs) -> None:
        """
        Synchronously give the current agent one or more related plain-language
        side-effecting actions.

        The actions argument must be a literal list or tuple of strings in
        workflow source and must contain at least one string. Multiple strings
        are prompt decomposition inside one model-facing task, not workflow
        control flow.
        """
        raise NotImplementedError

    def context(self, facts: dict[str, object] | None = None, **kwargs: object) -> Any:
        """
        Narrow or disambiguate named input facts for enclosed evaluate calls.

        Normal Python lexical scope is already evaluation context. Use this only
        when a workflow needs to deliberately narrow or clarify that scope.
        """
        raise NotImplementedError

    def evaluate(self, subject: str | type[Any]) -> Any:
        """
        Non-mutating model judgment over current context.

        For direct facts, subject is one declarative string and the assigned
        variable annotation must be bool, int, float, str, Literal[...] or
        list[...] over a basic scalar type. For structured facts, subject is a
        dataclass schema whose fields use Value(...) descriptions, and the
        assigned variable annotation must match the schema.
        """
        raise NotImplementedError

    def run_tool(self, name: str, **kwargs) -> Any:
        """Synchronously execute one specific registered tool."""
        raise NotImplementedError

    async def start_tool(self, name: str, **kwargs) -> Any:
        """Launch one specific registered tool and return a job handle."""
        raise NotImplementedError

    async def wait_all(self, jobs, timeout_seconds=None) -> Any:
        """Wait for every job, or raise a timeout failure."""
        raise NotImplementedError

    async def wait_any(self, jobs, timeout_seconds=None) -> Any:
        """Return completed jobs without cancelling unfinished jobs."""
        raise NotImplementedError

    def cancel(self, job) -> None:
        """Request cancellation and record the cancellation attempt."""
        raise NotImplementedError

    def lock(self, name) -> Any:
        """Serialize a critical section for the named runtime scope."""
        raise NotImplementedError

    def timeout(self, seconds) -> Any:
        """Bound the enclosed operation and raise on timeout."""
        raise NotImplementedError

    async def ask_user(self, prompt: str, **kwargs) -> Any:
        """Suspend for user input, then resume with a structured response."""
        raise NotImplementedError
