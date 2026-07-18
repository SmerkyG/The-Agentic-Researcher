"""Generic executor for model-free imperative operation workflows."""

from __future__ import annotations

from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait as futures_wait
from contextvars import ContextVar, Token
import json
import subprocess
from typing import Any, TypeVar, get_args, get_origin

import yaml

from agentic_tools import PythonTool, decode_value, record_data, record_from_data
from agentic_workflows.contract import (
    AgentVisibility,
    AgentWorkflow,
    ArgvTool,
    CommandResult,
    ExecutableWorkflow,
    Job,
    Operation,
    YAMLArgvTool,
)


class OperationExecutionError(RuntimeError):
    """Raised when a composed operation cannot be executed safely."""


_CURRENT_EXECUTOR: ContextVar[OperationExecutor | None] = ContextVar(
    "agentic_workflows_executor",
    default=None,
)


def current_executor() -> OperationExecutor:
    executor = _CURRENT_EXECUTOR.get()
    if executor is None:
        raise OperationExecutionError("operation.run() requires an active executable-workflow runtime")
    return executor


def operation_result_type(operation_type: type[Operation[Any]]) -> object:
    """Resolve the declared Operation[T] result type from generic bases."""

    visited: set[type[object]] = set()

    def visit(candidate: type[object], bindings: dict[TypeVar, object]) -> object | None:
        if candidate in visited:
            return None
        visited.add(candidate)
        for base in getattr(candidate, "__orig_bases__", ()):
            origin = get_origin(base) or base
            arguments = tuple(bindings.get(arg, arg) for arg in get_args(base))
            parameters = getattr(origin, "__parameters__", ())
            child_bindings = {**bindings, **dict(zip(parameters, arguments))}
            if origin is Operation and arguments:
                return arguments[0]
            if isinstance(origin, type):
                found = visit(origin, child_bindings)
                if found is not None:
                    if isinstance(found, TypeVar):
                        return child_bindings.get(found, found)
                    return found
        for base in candidate.__bases__:
            found = visit(base, bindings)
            if found is not None:
                return found
        return None

    return visit(operation_type, {}) or Any


class OperationExecutor:
    """Execute tools and nested executable workflows without model involvement."""

    def __init__(self, *, max_workers: int = 8) -> None:
        self._pool = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="operation-workflow")
        self._futures: dict[int, Future[Any]] = {}
        self._next_job_id = 1

    def __enter__(self) -> OperationExecutor:
        self._token = _CURRENT_EXECUTOR.set(self)
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        _CURRENT_EXECUTOR.reset(self._token)
        self._pool.shutdown(wait=True, cancel_futures=exc is not None)

    def _with_context(self, operation: Operation[Any]) -> object:
        token: Token[OperationExecutor | None] = _CURRENT_EXECUTOR.set(self)
        try:
            return self._run(operation)
        finally:
            _CURRENT_EXECUTOR.reset(token)

    def run(
        self,
        operation: Operation[Any],
        *,
        agent_visibility: AgentVisibility | None = None,
    ) -> Any:
        return self._run(operation)

    def _run(self, operation: Operation[Any]) -> Any:
        if isinstance(operation, AgentWorkflow):
            raise OperationExecutionError(
                "the generic executable-workflow CLI cannot run or launch agent workflows"
            )
        if isinstance(operation, ExecutableWorkflow):
            return operation.workflow()
        if isinstance(operation, PythonTool):
            return operation.execute()
        if isinstance(operation, ArgvTool):
            return self._run_argv(operation)
        raise OperationExecutionError(f"unsupported operation type: {type(operation).__module__}:{type(operation).__qualname__}")

    def _run_argv(self, operation: ArgvTool[Any]) -> Any:
        input_text = None
        if isinstance(operation, YAMLArgvTool):
            input_text = yaml.safe_dump(record_data(operation), sort_keys=False, allow_unicode=False)
        result_type = operation_result_type(type(operation))
        try:
            result = subprocess.run(
                operation.argv(),
                input=input_text,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
        except OSError as error:
            if result_type is CommandResult:
                return CommandResult(returncode=127, stderr=str(error))
            raise OperationExecutionError(
                f"could not execute {' '.join(operation.argv())}: {error}"
            ) from error
        if result_type is CommandResult:
            return CommandResult(
                returncode=result.returncode,
                stdout=result.stdout,
                stderr=result.stderr,
            )
        if result.returncode != 0:
            detail = (result.stderr or result.stdout).strip()
            raise OperationExecutionError(f"{' '.join(operation.argv())} failed: {detail}")

        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError as error:
            raise OperationExecutionError(
                f"{' '.join(operation.argv())} returned non-JSON output: {result.stdout.strip()}"
            ) from error
        return decode_value(result_type, payload)

    def launch(
        self,
        operation: Operation[Any],
        *,
        agent_visibility: AgentVisibility | None = None,
    ) -> Job[Any]:
        if isinstance(operation, AgentWorkflow):
            raise OperationExecutionError(
                "the generic executable-workflow CLI cannot launch subagents; keep that launch in an agent workflow"
            )
        job = Job()
        job_id = self._next_job_id
        self._next_job_id += 1
        self._futures[job_id] = self._pool.submit(self._with_context, operation)
        setattr(job, "_operation_job_id", job_id)
        return job

    def _future(self, job: Job[Any]) -> Future[Any]:
        job_id = getattr(job, "_operation_job_id", None)
        if not isinstance(job_id, int) or job_id not in self._futures:
            raise OperationExecutionError("job does not belong to this executable-workflow runtime")
        return self._futures[job_id]

    def wait(self, job: Job[Any], *, timeout_seconds: float | None = None) -> Any:
        return self._future(job).result(timeout=timeout_seconds)

    def wait_all(self, jobs: list[Job[Any]] | tuple[Job[Any], ...], *, timeout_seconds: float | None = None) -> list[Any]:
        futures = [self._future(job) for job in jobs]
        done, pending = futures_wait(futures, timeout=timeout_seconds)
        if pending:
            raise TimeoutError("timed out waiting for executable-workflow jobs")
        return [future.result() for future in futures]

    def wait_any(self, jobs: list[Job[Any]] | tuple[Job[Any], ...], *, timeout_seconds: float | None = None) -> list[Any]:
        futures = [self._future(job) for job in jobs]
        done, _pending = futures_wait(futures, timeout=timeout_seconds, return_when=FIRST_COMPLETED)
        return [future.result() for future in futures if future in done]

    def cancel(self, job: Job[Any]) -> None:
        self._future(job).cancel()

    def fire_and_forget(
        self,
        operation: Operation[Any],
        *,
        agent_visibility: AgentVisibility | None = None,
    ) -> None:
        raise OperationExecutionError(
            "detached execution is unavailable in the generic CLI runtime; use a durable background tool or launch from an agent workflow"
        )
