"""Minimal public contract shared by agent and executable interpreters."""

from __future__ import annotations

from typing import Any, ClassVar, Generic, Sequence, TypeVar


ResultT = TypeVar("ResultT")
StartedResultT = TypeVar("StartedResultT")


def Value(
    description: str,
    *,
    guidance: str | None = None,
    default: object = ...,
    default_factory: object = ...,
) -> object:
    """Describe one typed structured field and declarative guidance."""
    ...


class WorkflowRecord:
    """Typed structured data whose annotated fields form its schema."""


class Job(WorkflowRecord, Generic[ResultT]):
    """Opaque handle used only to track progress and receive an async result."""


class OperationNotice(WorkflowRecord):
    """Instructions followed immediately before resuming an operation result."""

    instructions: str


class Operation(WorkflowRecord, Generic[ResultT]):
    """A typed tool or subagent invocation."""

    guidance: ClassVar[str] = ""

    def run(self) -> ResultT:
        """Start this tool or subagent synchronously and return its result."""
        ...


class CommandResult(WorkflowRecord):
    """Result from a command-backed operation."""

    returncode: int
    stdout: str = ""
    stderr: str = ""


class WorkflowTool(Operation[ResultT], Generic[ResultT]):
    """Generic typed tool operation."""


class ArgvTool(WorkflowTool[ResultT], Generic[ResultT]):
    """Run the exact argv returned by argv()."""

    argv_template: ClassVar[tuple[str, ...]]

    def argv(self) -> list[str]:
        """Return this operation's exact command argv."""
        ...


class YAMLArgvTool(ArgvTool[ResultT], Generic[ResultT]):
    """Run exact argv with this operation's structured fields as YAML stdin."""


class AgentWorkflow(Operation[ResultT], Generic[ResultT]):
    """A workflow with separate invocation and body semantics.

    A callable agent declares a public contract subclass containing its inputs
    and result type, then an implementation subclass overriding workflow(). The
    manifest pairs the two classes. At top-level startup, follow on_startup()
    and then workflow(). After compaction, follow on_compaction() and resume the
    interrupted workflow() statement. Normal Python scope remains available to
    later model operations in that context.
    """

    agent_name: ClassVar[str]

    def on_startup(self) -> None:
        """Follow once before workflow() at session startup."""
        ...

    def on_compaction(self) -> None:
        """Follow after compaction before resuming the interrupted statement."""
        ...

    def workflow(self) -> ResultT:
        """Follow or execute this agent context's workflow body."""
        ...

    def do(self, actions: Sequence[str], guidance: str | None = None) -> None:
        """Perform related side-effecting model actions synchronously.

        Each action is atomic English work, not hidden control flow. Guidance
        is declarative context and does not add ordering or branches.
        """
        ...

    def evaluate(self, subject: str, guidance: str | None = None) -> Any:
        """Make a non-mutating typed model judgment from current Python scope."""
        ...

    def fill(self, record_type: type[WorkflowRecord], guidance: str | None = None) -> Any:
        """Fill one typed record from current scope and field descriptions."""
        ...

    def launch(self, operation: Operation[StartedResultT]) -> Job[StartedResultT]:
        """Start a tool or named subagent asynchronously and return its tracked Job."""
        ...

    def fire_and_forget(self, operation: Operation[Any]) -> None:
        """Start asynchronously, discard its platform handle, and continue now.

        Immediately follow the next Python statement. Never wait for, poll,
        list, message, follow up with, or otherwise inspect this operation. No
        later action or response may depend on its completion or result.
        """
        ...

    def wait(self, job: Job[ResultT], timeout_seconds: float | None = None) -> ResultT:
        """Wait for one job and return its typed result."""
        ...

    def wait_all(self, jobs: Sequence[Job[Any]], timeout_seconds: float | None = None) -> list[Any]:
        """Wait for every job and return completion results."""
        ...

    def wait_any(self, jobs: Sequence[Job[Any]], timeout_seconds: float | None = None) -> list[Any]:
        """Return completed jobs without cancelling unfinished jobs."""
        ...

    def cancel(self, job: Job[Any]) -> None:
        """Request cancellation and record the attempt."""
        ...

    def lock(self, name: str) -> Any:
        """Serialize the enclosed critical section for the named scope."""
        ...

    def timeout(self, seconds: float) -> Any:
        """Bound the enclosed operation with an explicit timeout."""
        ...


class SubagentWorkflow(AgentWorkflow[ResultT], Generic[ResultT]):
    """A workflow that must run in a separately started subagent context.

    The child follows the contract named by agent_name and receives the typed
    constructor fields as its request. Preserve inherited history when the
    platform supports it. If a native named role cannot inherit history, a
    history fork must be explicitly directed to follow the named contract.
    The caller must never execute this workflow's body.
    """


class UserFacingWorkflow(AgentWorkflow[ResultT], Generic[ResultT]):
    """Top-level workflow permitted to pause for visible user input."""

    def ask_user(self, question: str, **kwargs: object) -> str:
        """Ask a specific question, suspend, and resume with the answer.

        Subagents must not ask the user. Describe the blocker or choice, why
        autonomous work cannot decide it, and the needed answer.
        """
        ...
