"""Persistent Python runtime for callback-managed agent workflows."""

from __future__ import annotations

from queue import Queue
from threading import Thread
from typing import Any, Mapping

from agentic_workflows.contract import AgentWorkflow, Job, Operation
from agentic_workflows.execution import (
    OperationExecutionError,
    OperationExecutor,
    decode_value,
    operation_result_type,
    record_data,
)
from agentic_workflows.fill_spec import (
    AgentRequestSpec,
    AgentRequestSpecBuilder,
    assignment_schema,
    decode_assignments,
    render_agent_request,
)


class CallbackBridge:
    """Blocking exchange between a live workflow stack and a CLI callback."""

    def __init__(self) -> None:
        self.events: Queue[dict[str, object]] = Queue()
        self.responses: Queue[dict[str, object]] = Queue()
        self._next_boundary = 1

    def exchange(self, kind: str, payload: Mapping[str, object]) -> dict[str, object]:
        boundary_id = str(self._next_boundary)
        self._next_boundary += 1
        self.events.put(
            {
                "status": kind,
                "boundary_id": boundary_id,
                **payload,
            }
        )
        return self.responses.get()


class CallbackOperationExecutor(OperationExecutor):
    """Operation executor whose model and native-agent boundaries use callbacks."""

    def __init__(self, bridge: CallbackBridge) -> None:
        super().__init__()
        self.bridge = bridge
        self._observations: dict[str, object] = {}
        self._admitted_jobs: set[int] = set()

    def agent_request(self, *, name: str | None = None) -> AgentRequestSpecBuilder:
        observations = dict(self._observations)

        def complete(spec: AgentRequestSpec) -> Mapping[str, object]:
            self._observations.clear()
            validation_error: str | None = None
            while True:
                payload: dict[str, object] = {
                    "instructions": render_agent_request(spec),
                    "response_schema": assignment_schema(spec),
                }
                if validation_error:
                    payload["validation_error"] = validation_error
                response = self.bridge.exchange("agent_request", payload)
                assignments = response.get("assignments", response)
                if not isinstance(assignments, Mapping):
                    validation_error = "resume payload must be an assignments object"
                    continue
                try:
                    _variables, returned = decode_assignments(spec, assignments)
                except (TypeError, ValueError) as error:
                    validation_error = str(error)
                    continue
                return returned

        return AgentRequestSpecBuilder(
            name,
            initial_observations=observations,
            on_complete=complete,
        )

    def _run(self, operation: Operation[Any]) -> Any:
        if not isinstance(operation, AgentWorkflow):
            return super()._run(operation)
        response = self.bridge.exchange(
            "subagent_run",
            {
                "agent_name": operation.agent_name,
                "operation_type": f"{type(operation).__module__}:{type(operation).__qualname__}",
                "inputs": record_data(operation),
                "instructions": (
                    f"Run the named `{operation.agent_name}` subagent with exactly the supplied "
                    "typed inputs and wait for its typed result."
                ),
            },
        )
        if "error" in response:
            raise OperationExecutionError(str(response["error"]))
        if "result" not in response:
            raise OperationExecutionError("subagent_run resume payload requires result")
        return decode_value(operation_result_type(type(operation)), response["result"])

    def observe(self, **values: object) -> None:
        if not values:
            raise OperationExecutionError("observe() requires at least one named value")
        overlap = sorted(set(values) & set(self._observations))
        if overlap:
            raise OperationExecutionError(
                "duplicate pending observations: " + ", ".join(overlap)
            )
        self._observations.update(values)

    def ask_user(self, question: str, **kwargs: object) -> str:
        response = self.bridge.exchange(
            "ask_user",
            {
                "question": question,
                "options": record_data(kwargs),
            },
        )
        answer = response.get("answer")
        if not isinstance(answer, str):
            raise OperationExecutionError("ask_user resume payload requires a string answer")
        return answer

    def admit(self, operation: Operation[Any]) -> Job[Any]:
        if not isinstance(operation, AgentWorkflow):
            return self.launch(operation)
        response = self.bridge.exchange(
            "subagent_admission",
            {
                "agent_name": operation.agent_name,
                "operation_type": f"{type(operation).__module__}:{type(operation).__qualname__}",
                "inputs": record_data(operation),
                "instructions": (
                    f"Start the named `{operation.agent_name}` subagent with exactly the supplied "
                    "typed inputs. Resume only after its launcher has accepted the request."
                ),
            },
        )
        if response.get("accepted") is not True:
            reason = response.get("error", "subagent admission was rejected")
            raise OperationExecutionError(str(reason))
        job: Job[Any] = Job()
        marker = id(job)
        self._admitted_jobs.add(marker)
        setattr(job, "_callback_admission_id", marker)
        setattr(job, "_callback_native_handle", response.get("handle"))
        return job

    def detach(self, job: Job[Any]) -> None:
        marker = getattr(job, "_callback_admission_id", None)
        if marker not in self._admitted_jobs:
            raise OperationExecutionError("detach() requires a job returned by admit()")
        self._admitted_jobs.remove(marker)

    def fire_and_forget(self, operation: Operation[Any]) -> None:
        if isinstance(operation, AgentWorkflow):
            self.detach(self.admit(operation))
            return
        super().fire_and_forget(operation)


class WorkflowThread:
    """Own one live Python workflow stack until it returns or fails."""

    def __init__(self, workflow: AgentWorkflow[Any]) -> None:
        self.workflow = workflow
        self.bridge = CallbackBridge()
        self.thread = Thread(target=self._run, name="agent-workflow", daemon=True)

    def start(self) -> dict[str, object]:
        self.thread.start()
        return self.bridge.events.get()

    def resume(self, payload: Mapping[str, object]) -> dict[str, object]:
        self.bridge.responses.put(dict(payload))
        return self.bridge.events.get()

    def _run(self) -> None:
        try:
            with CallbackOperationExecutor(self.bridge):
                self.workflow.on_startup()
                result = self.workflow.workflow()
            self.bridge.events.put(
                {
                    "status": "complete",
                    "boundary_id": None,
                    "result": record_data(result),
                }
            )
        except BaseException as error:
            self.bridge.events.put(
                {
                    "status": "failed",
                    "boundary_id": None,
                    "error": f"{type(error).__name__}: {error}",
                }
            )
