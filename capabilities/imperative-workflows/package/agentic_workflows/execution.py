"""Generic executor for model-free imperative operation workflows."""

from __future__ import annotations

from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait as futures_wait
from contextvars import ContextVar, Token
from dataclasses import fields, is_dataclass
import json
import subprocess
import types
from typing import Any, Literal, TypeVar, Union, get_args, get_origin, get_type_hints

import yaml

from agentic_workflows.contract import (
    AgentWorkflow,
    ArgvTool,
    CommandResult,
    ExecutableWorkflow,
    Job,
    Operation,
    WorkflowRecord,
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


def record_data(value: object) -> object:
    """Convert workflow records into JSON/YAML-compatible values."""

    if isinstance(value, WorkflowRecord) and is_dataclass(value):
        return {
            item.name: record_data(getattr(value, item.name))
            for item in fields(value)
            if getattr(value, item.name) is not None
        }
    if isinstance(value, list):
        return [record_data(item) for item in value]
    if isinstance(value, tuple):
        return [record_data(item) for item in value]
    if isinstance(value, dict):
        return {str(key): record_data(item) for key, item in value.items() if item is not None}
    return value


def decode_value(annotation: object, value: object) -> object:
    """Decode one JSON-compatible value according to a workflow annotation."""

    if annotation in {Any, object}:
        return value
    origin = get_origin(annotation)
    args = get_args(annotation)
    if origin is Literal:
        if value not in args:
            raise ValueError(f"expected one of {args!r}, got {value!r}")
        return value
    if origin in {list, tuple}:
        if not isinstance(value, (list, tuple)):
            raise TypeError(f"expected an array, got {type(value).__name__}")
        item_type = args[0] if args else Any
        decoded = [decode_value(item_type, item) for item in value]
        return tuple(decoded) if origin is tuple else decoded
    if origin in {Union, types.UnionType}:
        if value is None and type(None) in args:
            return None
        for candidate in args:
            if candidate is type(None):
                continue
            try:
                if (
                    isinstance(candidate, type)
                    and issubclass(candidate, WorkflowRecord)
                    and isinstance(value, dict)
                ):
                    return record_from_data(candidate, value, reject_unknown=True)
                return decode_value(candidate, value)
            except (TypeError, ValueError):
                continue
        return value
    if isinstance(annotation, type) and issubclass(annotation, WorkflowRecord):
        if not isinstance(value, dict):
            raise TypeError(f"{annotation.__name__} requires an object result")
        return record_from_data(annotation, value)
    if annotation is type(None):
        if value is not None:
            raise TypeError(f"expected null, got {type(value).__name__}")
        return None
    if annotation in {str, int, float, bool}:
        valid = isinstance(value, annotation)
        if annotation in {int, float} and isinstance(value, bool):
            valid = False
        if annotation is float and isinstance(value, int) and not isinstance(value, bool):
            return float(value)
        if not valid:
            raise TypeError(f"expected {annotation.__name__}, got {type(value).__name__}")
        return value
    return value


def record_from_data(
    record_type: type[WorkflowRecord],
    data: dict[str, object],
    *,
    reject_unknown: bool = False,
) -> WorkflowRecord:
    """Construct a typed workflow record, ignoring command response metadata."""

    if not is_dataclass(record_type):
        raise TypeError(f"workflow record is not a dataclass: {record_type.__name__}")
    field_names = {item.name for item in fields(record_type)}
    unknown = sorted(set(data) - field_names)
    if reject_unknown and unknown:
        raise TypeError(f"unexpected {record_type.__name__} fields: {', '.join(unknown)}")
    hints = get_type_hints(record_type)
    values = {
            item.name: decode_value(hints.get(item.name, item.type), data[item.name])
        for item in fields(record_type)
        if item.name in data
    }
    return record_type(**values)


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

    def run(self, operation: Operation[Any]) -> Any:
        return self._run(operation)

    def _run(self, operation: Operation[Any]) -> Any:
        if isinstance(operation, AgentWorkflow):
            raise OperationExecutionError(
                "the generic executable-workflow CLI cannot run or launch agent workflows"
            )
        if isinstance(operation, ExecutableWorkflow):
            return operation.workflow()
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

    def launch(self, operation: Operation[Any]) -> Job[Any]:
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

    def fire_and_forget(self, operation: Operation[Any]) -> None:
        raise OperationExecutionError(
            "detached execution is unavailable in the generic CLI runtime; use a durable background tool or launch from an agent workflow"
        )
