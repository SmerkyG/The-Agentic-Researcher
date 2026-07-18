"""Persistent Python runtime for callback-managed agent workflows."""

from __future__ import annotations

from contextvars import ContextVar, Token
from queue import Queue
from threading import Thread
from typing import Any, Mapping

from agentic_workflows.contract import AgentVisibility, AgentWorkflow, Job, Operation
from agentic_workflows.execution import (
    OperationExecutionError,
    OperationExecutor,
    decode_value,
    operation_result_type,
    record_data,
)
from agentic_workflows.request_spec import (
    AgentRequest,
    AgentObservation,
    AgentRequestSpec,
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
        self._queued_agent_observations: list[AgentObservation] = []
        self._admitted_jobs: set[int] = set()
        self._operation_depth: ContextVar[int] = ContextVar(
            "agentic_workflows_callback_operation_depth",
            default=0,
        )

    def _effective_visibility(
        self,
        operation: Operation[Any],
        override: AgentVisibility | None,
    ) -> AgentVisibility:
        visibility = override or operation.agent_visibility
        if visibility not in {"shown", "hidden"}:
            raise OperationExecutionError(
                f"invalid agent visibility for {type(operation).__name__}: {visibility!r}"
            )
        return visibility

    def _operation_value(
        self,
        operation: Operation[Any],
        *,
        status: str,
        result: object = ...,
        error: str | None = None,
    ) -> dict[str, object]:
        operation_type = f"{type(operation).__module__}:{type(operation).__qualname__}"
        value: dict[str, object] = {
            "operation": operation_type,
            "action": (type(operation).__doc__ or "").strip().split("\n", 1)[0],
            "inputs": record_data(operation),
            "status": status,
        }
        if result is not ...:
            value["result"] = operation.agent_observation(result)
        if error is not None:
            value["error"] = error
        return value

    def _queue_operation_observation(
        self,
        operation: Operation[Any],
        *,
        status: str,
        result: object = ...,
        error: str | None = None,
    ) -> AgentObservation:
        observation = AgentObservation(
            value=self._operation_value(
                operation,
                status=status,
                result=result,
                error=error,
            )
        )
        self._queued_agent_observations.append(observation)
        return observation

    def _replace_or_queue_job_observation(
        self,
        job: Job[Any],
        result: object,
    ) -> None:
        if getattr(job, "_agent_completion_observed", False):
            return
        operation = getattr(job, "_agent_observation_operation", None)
        visibility = getattr(job, "_agent_observation_visibility", "hidden")
        top_level = getattr(job, "_agent_observation_top_level", False)
        if (
            not isinstance(operation, Operation)
            or visibility != "shown"
            or not top_level
        ):
            setattr(job, "_agent_completion_observed", True)
            return
        completed = AgentObservation(
            value=self._operation_value(
                operation,
                status="completed",
                result=result,
            )
        )
        launched = getattr(job, "_agent_launch_observation", None)
        for index, pending in enumerate(self._queued_agent_observations):
            if pending is launched:
                self._queued_agent_observations[index] = completed
                break
        else:
            self._queued_agent_observations.append(completed)
        setattr(job, "_agent_launch_observation", completed)
        setattr(job, "_agent_completion_observed", True)

    def _with_context(self, operation: Operation[Any]) -> object:
        token: Token[int] = self._operation_depth.set(1)
        try:
            return super()._with_context(operation)
        finally:
            self._operation_depth.reset(token)

    def run(
        self,
        operation: Operation[Any],
        *,
        agent_visibility: AgentVisibility | None = None,
    ) -> Any:
        visibility = self._effective_visibility(operation, agent_visibility)
        depth = self._operation_depth.get()
        token: Token[int] = self._operation_depth.set(depth + 1)
        try:
            result = self._run(operation)
        except BaseException as error:
            if depth == 0 and visibility == "shown":
                self._queue_operation_observation(
                    operation,
                    status="failed",
                    error=f"{type(error).__name__}: {error}",
                )
            raise
        finally:
            self._operation_depth.reset(token)
        if depth == 0 and visibility == "shown":
            self._queue_operation_observation(
                operation,
                status="completed",
                result=result,
            )
        return result

    def launch(
        self,
        operation: Operation[Any],
        *,
        agent_visibility: AgentVisibility | None = None,
    ) -> Job[Any]:
        visibility = self._effective_visibility(operation, agent_visibility)
        job = super().launch(operation, agent_visibility=visibility)
        setattr(job, "_agent_observation_operation", operation)
        setattr(job, "_agent_observation_visibility", visibility)
        top_level = self._operation_depth.get() == 0
        setattr(job, "_agent_observation_top_level", top_level)
        if top_level and visibility == "shown":
            launched = self._queue_operation_observation(
                operation,
                status="launched",
            )
            setattr(job, "_agent_launch_observation", launched)
        return job

    def wait(
        self,
        job: Job[Any],
        *,
        timeout_seconds: float | None = None,
    ) -> Any:
        result = super().wait(job, timeout_seconds=timeout_seconds)
        self._replace_or_queue_job_observation(job, result)
        return result

    def wait_all(
        self,
        jobs: list[Job[Any]] | tuple[Job[Any], ...],
        *,
        timeout_seconds: float | None = None,
    ) -> list[Any]:
        results = super().wait_all(jobs, timeout_seconds=timeout_seconds)
        for job, result in zip(jobs, results):
            self._replace_or_queue_job_observation(job, result)
        return results

    def wait_any(
        self,
        jobs: list[Job[Any]] | tuple[Job[Any], ...],
        *,
        timeout_seconds: float | None = None,
    ) -> list[Any]:
        results = super().wait_any(jobs, timeout_seconds=timeout_seconds)
        completed_jobs = [job for job in jobs if self._future(job).done()]
        for job, result in zip(completed_jobs, results):
            self._replace_or_queue_job_observation(job, result)
        return results

    def _complete_agent_request(self, spec: AgentRequestSpec) -> Mapping[str, object]:
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

    def agent_request(
        self,
        request_type: type[AgentRequest],
        *,
        name: str | None = None,
    ) -> object:
        if not isinstance(request_type, type) or not issubclass(request_type, AgentRequest):
            raise OperationExecutionError(
                "agent_request() requires an AgentRequest subclass"
            )
        declared = request_type.__request_spec__
        observations = tuple(self._queued_agent_observations)
        spec = AgentRequestSpec(
            declared.items,
            name=name or declared.name,
            observations=observations,
        )
        self._queued_agent_observations.clear()
        returned = self._complete_agent_request(spec)
        instance = request_type()
        for field_name, value in returned.items():
            setattr(instance, field_name, value)
        return instance

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

    def queue_agent_observation(
        self,
        value: object,
        *,
        desc: str | None = None,
    ) -> None:
        self._queued_agent_observations.append(
            AgentObservation(value=value, desc=desc, must_consume=True)
        )

    def ensure_no_queued_agent_observations(self) -> None:
        if any(
            observation.must_consume
            for observation in self._queued_agent_observations
        ):
            raise OperationExecutionError(
                "workflow completed with unconsumed queued agent observations"
            )

    def ask_user(self, question: str, **kwargs: object) -> str:
        response = self.bridge.exchange(
            "ask_user",
            {
                "instructions": question,
                "options": record_data(kwargs),
            },
        )
        answer = response.get("answer")
        if not isinstance(answer, str):
            raise OperationExecutionError("ask_user resume payload requires a string answer")
        return answer

    def admit(
        self,
        operation: Operation[Any],
        *,
        agent_visibility: AgentVisibility | None = None,
    ) -> Job[Any]:
        visibility = self._effective_visibility(operation, agent_visibility)
        if not isinstance(operation, AgentWorkflow):
            return self.launch(operation, agent_visibility=visibility)
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
        setattr(job, "_agent_observation_operation", operation)
        setattr(job, "_agent_observation_visibility", visibility)
        setattr(job, "_agent_observation_top_level", True)
        if visibility == "shown":
            accepted = self._queue_operation_observation(
                operation,
                status="accepted",
            )
            setattr(job, "_agent_launch_observation", accepted)
        return job

    def detach(self, job: Job[Any]) -> None:
        marker = getattr(job, "_callback_admission_id", None)
        if marker not in self._admitted_jobs:
            raise OperationExecutionError("detach() requires a job returned by admit()")
        self._admitted_jobs.remove(marker)

    def fire_and_forget(
        self,
        operation: Operation[Any],
        *,
        agent_visibility: AgentVisibility | None = None,
    ) -> None:
        if isinstance(operation, AgentWorkflow):
            self.detach(
                self.admit(operation, agent_visibility=agent_visibility)
            )
            return
        super().fire_and_forget(
            operation,
            agent_visibility=agent_visibility,
        )


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
            with CallbackOperationExecutor(self.bridge) as executor:
                self.workflow.on_startup()
                result = self.workflow.workflow()
                executor.ensure_no_queued_agent_observations()
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
