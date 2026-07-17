"""Minimal public contract shared by agent and executable interpreters."""

from __future__ import annotations

from dataclasses import dataclass, field
import importlib
from typing import Any, ClassVar, Generic, Sequence, TypeVar


ResultT = TypeVar("ResultT")
StartedResultT = TypeVar("StartedResultT")
ContractT = TypeVar("ContractT")


def _current_executor() -> Any:
    """Resolve the optional executable runtime without publishing it as workflow source."""

    return importlib.import_module("agentic_workflows.execution").current_executor()


def Value(
    description: str,
    *,
    guidance: str | None = None,
    default: object = ...,
    default_factory: object = ...,
) -> object:
    """Describe one typed structured field and declarative guidance."""
    metadata = {"description": description}
    if guidance is not None:
        metadata["guidance"] = guidance
    kwargs: dict[str, object] = {"metadata": metadata}
    if default is not ...:
        kwargs["default"] = default
    if default_factory is not ...:
        kwargs["default_factory"] = default_factory
    return field(**kwargs)


class WorkflowRecord:
    """Typed structured data whose annotated fields form its schema."""

    def __init_subclass__(cls, **kwargs: object) -> None:
        super().__init_subclass__(**kwargs)
        if "__dataclass_fields__" not in cls.__dict__:
            dataclass(cls)


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
        return _current_executor().run(self)


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
        return list(self.argv_template)


class YAMLArgvTool(ArgvTool[ResultT], Generic[ResultT]):
    """Run exact argv with declared fields serialized as YAML stdin.

    The operation owns serialization. Do not invent fields or hand-format YAML.
    In agent-follow mode without native structured dispatch, encode the declared
    field values as JSON stdin, which is valid YAML and safely quotes strings.
    """


class Workflow(Operation[ResultT], Generic[ResultT]):
    """Shared synchronous and tracked-asynchronous workflow vocabulary."""

    def workflow(self) -> ResultT:
        """Execute or follow this workflow's body."""
        raise NotImplementedError

    def launch(self, operation: Operation[StartedResultT]) -> Job[StartedResultT]:
        """Start a non-agent operation asynchronously and return a tracked job."""
        return _current_executor().launch(operation)

    def fire_and_forget(self, operation: Operation[Any]) -> None:
        """Start asynchronously, discard its platform handle, and continue now.

        AgentWorkflow callers immediately follow the next Python statement.
        Never wait, poll, list, message, follow up with, or depend on that
        operation. Executable runtimes may reject detached execution when they
        cannot make the launch durable.
        """
        _current_executor().fire_and_forget(operation)

    def wait(self, job: Job[ResultT], timeout_seconds: float | None = None) -> ResultT:
        """Wait for one tracked job."""
        return _current_executor().wait(job, timeout_seconds=timeout_seconds)

    def wait_all(self, jobs: Sequence[Job[Any]], timeout_seconds: float | None = None) -> list[Any]:
        """Wait for every tracked job."""
        return _current_executor().wait_all(jobs, timeout_seconds=timeout_seconds)

    def wait_any(self, jobs: Sequence[Job[Any]], timeout_seconds: float | None = None) -> list[Any]:
        """Return results from tracked jobs that have completed."""
        return _current_executor().wait_any(jobs, timeout_seconds=timeout_seconds)

    def cancel(self, job: Job[Any]) -> None:
        """Request cancellation of a tracked job."""
        _current_executor().cancel(job)


class ExecutableWorkflow(YAMLArgvTool[ResultT], Workflow[ResultT], Generic[ResultT]):
    """Model-free Python orchestration over typed operations.

    Callers execute the exact argv returned by argv() with the declared fields
    serialized as YAML stdin. They must attempt that invocation directly,
    without preliminary CLI help, command discovery, implementation inspection,
    or manual decomposition.

    The generic CLI executor supports tools, nested executable workflows, and
    tracked parallel tool calls. It intentionally rejects AgentWorkflow and
    SubagentWorkflow operations until a subagent-capable executor is available.
    """

    workflow_implementation: ClassVar[str]

    def argv(self) -> list[str]:
        symbol = f"{type(self).__module__}:{type(self).__qualname__}"
        return ["imperative-workflows-run", symbol]


class ExecutableWorkflowImplementation(Generic[ContractT]):
    """Marker mixed into a private implementation of an executable contract."""


class AgentWorkflow(Workflow[ResultT], Generic[ResultT]):
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

    def agent_request(self, name: str | None = None) -> Any:
        """Declare one aggregate model boundary with ordered declarative nodes.

        The returned context manager accepts ``observe``, ``step``, ``var``,
        ``field``, and nested ``guidance`` declarations.  It submits the whole
        request only after successful block exit.  Values declared with
        ``field`` are then available as attributes on the context-manager value.
        """
        return _current_executor().agent_request(name=name)

    def observe(self, **values: object) -> None:
        """Retain external operation results for the next agent request."""
        _current_executor().observe(**values)

    def admit(self, operation: Operation[StartedResultT]) -> Job[StartedResultT]:
        """Obtain receiver-side acceptance for an asynchronously launched operation."""
        return _current_executor().admit(operation)

    def detach(self, job: Job[Any]) -> None:
        """Transfer lifecycle ownership of an admitted operation to the launcher."""
        _current_executor().detach(job)

    def lock(self, name: str) -> Any:
        """Serialize the enclosed critical section for the named scope."""
        ...

    def timeout(self, seconds: float) -> Any:
        """Bound the enclosed operation with an explicit timeout."""
        ...


class SubagentWorkflow(AgentWorkflow[ResultT], Generic[ResultT]):
    """A workflow that must run in a separately started subagent context.

    The child follows the contract named by agent_name and receives the typed
    constructor fields as its request. The caller resolves agent_name through
    the Available Subagents catalog and uses its matching Contract path; it
    must not search the filesystem or installation for an agent contract.
    Preserve inherited history when the platform supports it. If a native named
    role cannot inherit history, a history fork must receive that exact rendered
    contract path and be explicitly directed to follow it. The child reads that
    path directly and must not search for another contract. The caller must
    never execute this workflow's body.
    """


class UserFacingWorkflow(AgentWorkflow[ResultT], Generic[ResultT]):
    """Top-level workflow permitted to pause for visible user input."""

    def ask_user(self, question: str, **kwargs: object) -> str:
        """Ask a specific question, suspend, and resume with the answer.

        Subagents must not ask the user. Describe the blocker or choice, why
        autonomous work cannot decide it, and the needed answer.
        """
        return _current_executor().ask_user(question, **kwargs)
