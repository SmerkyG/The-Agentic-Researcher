"""Minimal public contract shared by agent and executable interpreters."""

from __future__ import annotations

import importlib
from typing import Any, ClassVar, Generic, Sequence, TypeVar

from agentic_tools import (
    AgentVisibility,
    Operation,
    PythonTool,
    Record as WorkflowRecord,
    Value,
)


ResultT = TypeVar("ResultT")
StartedResultT = TypeVar("StartedResultT")


def _current_executor() -> Any:
    return importlib.import_module("agentic_workflows.execution").current_executor()


class Job(WorkflowRecord, Generic[ResultT]):
    """Opaque handle used only to track progress and receive an async result."""


class OperationNotice(WorkflowRecord):
    """Instructions followed immediately before resuming an operation result."""

    instructions: str


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
    Encode declared field values as JSON stdin, which is valid YAML and safely
    quotes strings.
    """


class Workflow(Operation[ResultT], Generic[ResultT]):
    """Shared synchronous and tracked-asynchronous workflow vocabulary."""

    def workflow(self) -> ResultT:
        """Execute this workflow's body."""
        raise NotImplementedError

    def launch(
        self,
        operation: Operation[StartedResultT],
        *,
        agent_visibility: AgentVisibility | None = None,
    ) -> Job[StartedResultT]:
        """Start a non-agent operation asynchronously and return a tracked job."""
        return _current_executor().launch(
            operation,
            agent_visibility=agent_visibility,
        )

    def fire_and_forget(
        self,
        operation: Operation[Any],
        *,
        agent_visibility: AgentVisibility | None = None,
    ) -> None:
        """Start asynchronously, discard its platform handle, and continue now.

        AgentWorkflow workers immediately execute the next Python statement.
        Never wait, poll, list, message, follow up with, or depend on that
        operation. Executable runtimes may reject detached execution when they
        cannot make the launch durable.
        """
        _current_executor().fire_and_forget(
            operation,
            agent_visibility=agent_visibility,
        )

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

    def argv(self) -> list[str]:
        symbol = f"{type(self).__module__}:{type(self).__qualname__}"
        return ["imperative-workflows-run", symbol]


class AgentWorkflow(Workflow[ResultT], Generic[ResultT]):
    """One executable agent contract and workflow implementation.

    The same class declares typed constructor inputs, result type, and
    workflow(). A callback worker executes on_startup() and workflow(), retaining
    its Python stack across model and user boundaries. After compaction it
    executes on_compaction() before resuming the interrupted statement.
    """

    agent_name: ClassVar[str]

    def on_startup(self) -> None:
        """Execute once before workflow() at session startup."""
        ...

    def on_compaction(self) -> None:
        """Execute after compaction before resuming the interrupted statement."""
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

    def agent_request(
        self,
        request_type: type[Any],
        name: str | None = None,
        *,
        tools: Sequence[type[PythonTool[Any]]] = (),
        detachable_tools: Sequence[type[PythonTool[Any]]] = (),
    ) -> Any:
        """Execute a class-declared aggregate model boundary.

        ``request_type`` is an ``AgentRequest`` subclass whose ordered class body
        contains ``step``, ``local``, ``result``, and nested ``guidance``
        declarations. Returned results are available as attributes on the
        resulting request instance. Previously queued external observations are
        supplied as a preamble to this boundary. ``tools`` grants request-scoped
        access to registered PythonTools. ``detachable_tools`` must be a subset
        of that grant and permits the agent to request executor-owned detached
        launch instead of waiting for a result.

        """
        return _current_executor().agent_request(
            request_type,
            name=name,
            tools=tools,
            detachable_tools=detachable_tools,
        )

    def queue_agent_observation(
        self,
        value: object,
        *,
        desc: str | None = None,
    ) -> None:
        """Queue one external value for exactly the next agent request."""
        _current_executor().queue_agent_observation(value, desc=desc)

    def admit(
        self,
        operation: Operation[StartedResultT],
        *,
        agent_visibility: AgentVisibility | None = None,
    ) -> Job[StartedResultT]:
        """Obtain receiver-side acceptance for an asynchronously launched operation."""
        return _current_executor().admit(
            operation,
            agent_visibility=agent_visibility,
        )

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

    The runtime emits a native subagent boundary containing agent_name and the
    typed constructor fields. The adapter starts the child and must never
    execute this workflow body in the caller's worker or model context.
    """


class UserFacingWorkflow(AgentWorkflow[ResultT], Generic[ResultT]):
    """Top-level workflow permitted to pause for visible user input."""

    def ask_user(self, question: str, **kwargs: object) -> str:
        """Have the agent formulate a user-facing question, suspend, and resume.

        ``question`` is a model-facing contract, not necessarily verbatim user
        prose. Describe what the prompt must establish, relevant context and
        constraints, and the answer needed. The agent renders the final concise
        prompt from its retained context. Subagents must not ask the user.
        """
        return _current_executor().ask_user(question, **kwargs)
