"""Persistent Python runtime for callback-managed agent workflows."""

from __future__ import annotations

from contextvars import ContextVar, Token
import hashlib
import json
from queue import Queue
import subprocess
import sys
from threading import Thread
from typing import Any, Mapping, Sequence

from agentic_tools import PythonTool, record_data as tool_record_data, record_from_data
from agentic_tools.catalog import ToolRegistration, discover_tools, registrations_for_types
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
        self._tool_catalog = discover_tools()
        self._known_agent_tool_definitions: dict[str, str] = {}
        self._active_agent_tool_grants: dict[str, ToolRegistration] = {}
        self._detached_tool_processes: list[subprocess.Popen[str]] = []
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

    def _tool_grants(
        self,
        tools: Sequence[type[PythonTool[Any]]],
        detachable_tools: Sequence[type[PythonTool[Any]]],
    ) -> tuple[dict[str, ToolRegistration], set[str]]:
        granted_types = tuple(tools)
        detachable_types = tuple(detachable_tools)
        unknown_detachable = [
            tool_type for tool_type in detachable_types if tool_type not in granted_types
        ]
        if unknown_detachable:
            names = ", ".join(
                f"{item.__module__}:{item.__qualname__}" for item in unknown_detachable
            )
            raise OperationExecutionError(
                f"detachable_tools must be included in tools: {names}"
            )
        try:
            grants = registrations_for_types(
                list(granted_types),
                registrations=self._tool_catalog,
            )
            detachable = registrations_for_types(
                list(detachable_types),
                registrations=self._tool_catalog,
            )
        except (TypeError, ValueError) as error:
            raise OperationExecutionError(str(error)) from error
        return grants, set(detachable)

    def _tool_definition_hash(self, definition: Mapping[str, object]) -> str:
        encoded = json.dumps(
            dict(definition),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def _tool_request_schema(
        self,
        grants: Mapping[str, ToolRegistration],
        detachable: set[str],
    ) -> dict[str, object]:
        variants: list[dict[str, object]] = []
        for name, registration in grants.items():
            modes = ["await", "detach"] if name in detachable else ["await"]
            variants.append(
                {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string", "minLength": 1},
                        "tool": {"const": name},
                        "arguments": registration.definition()["input_schema"],
                        "mode": {"enum": modes},
                    },
                    "required": ["id", "tool", "arguments", "mode"],
                    "additionalProperties": False,
                }
            )
        return {
            "type": "object",
            "properties": {
                "kind": {"const": "tool_requests"},
                "requests": {
                    "type": "array",
                    "minItems": 1,
                    "items": {"oneOf": variants},
                },
            },
            "required": ["kind", "requests"],
            "additionalProperties": False,
        }

    def _agent_request_payload(
        self,
        spec: AgentRequestSpec,
        grants: Mapping[str, ToolRegistration],
        detachable: set[str],
        *,
        validation_error: str | None = None,
        tool_results: list[dict[str, object]] | None = None,
    ) -> dict[str, object]:
        self._active_agent_tool_grants = dict(grants)
        definitions: dict[str, object] = {}
        definition_hashes: dict[str, str] = {}
        for name, registration in grants.items():
            definition = registration.definition()
            digest = self._tool_definition_hash(definition)
            definition_hashes[name] = digest
            if self._known_agent_tool_definitions.get(name) != digest:
                definitions[name] = definition

        instructions = render_agent_request(spec)
        if grants:
            instructions += (
                "\nThis request may return a tool-request packet before its final "
                "assignments. Use only names in `available_tools`. Full definitions "
                "appear in `tool_definitions` when new or changed; otherwise the name "
                "refers to the definition already supplied in this agent context. "
                "Return `mode: \"detach\"` only when that mode is explicitly granted.\n"
            )
        if tool_results:
            instructions += (
                "\nContinue the same request using these completed tool results. Do not "
                "repeat a detached request or depend on its eventual result:\n"
                + json.dumps(tool_results, indent=2, ensure_ascii=False)
                + "\n"
            )

        payload: dict[str, object] = {
            "instructions": instructions,
            "response_schema": assignment_schema(spec),
        }
        if grants:
            payload["available_tools"] = [
                {
                    "name": name,
                    "modes": ["await", "detach"] if name in detachable else ["await"],
                }
                for name in grants
            ]
            payload["tool_definitions"] = definitions
            payload["tool_request_schema"] = self._tool_request_schema(grants, detachable)
        if validation_error:
            payload["validation_error"] = validation_error
        if tool_results:
            payload["tool_results"] = tool_results

        # An enqueued callback event is durable and recoverable through status,
        # so its definitions count as supplied even if the MCP response is lost.
        self._known_agent_tool_definitions.update(definition_hashes)
        return payload

    def reset_agent_context(self, event: Mapping[str, object]) -> dict[str, object]:
        """Forget context-cached definitions and refresh one pending request event."""

        self._known_agent_tool_definitions.clear()
        refreshed = dict(event)
        if refreshed.get("status") != "agent_request" or not self._active_agent_tool_grants:
            return refreshed
        definitions = {
            name: registration.definition()
            for name, registration in self._active_agent_tool_grants.items()
        }
        refreshed["tool_definitions"] = definitions
        for name, definition in definitions.items():
            self._known_agent_tool_definitions[name] = self._tool_definition_hash(definition)
        return refreshed

    def _decode_tool_requests(
        self,
        response: Mapping[str, object],
        grants: Mapping[str, ToolRegistration],
        detachable: set[str],
    ) -> list[tuple[str, ToolRegistration, PythonTool[Any], str]]:
        raw_requests = response.get("requests")
        if not isinstance(raw_requests, list) or not raw_requests:
            raise ValueError("tool_requests requires a nonempty requests array")
        decoded: list[tuple[str, ToolRegistration, PythonTool[Any], str]] = []
        seen_ids: set[str] = set()
        for index, raw in enumerate(raw_requests):
            if not isinstance(raw, Mapping):
                raise TypeError(f"tool request {index + 1} must be an object")
            unknown = sorted(set(raw) - {"id", "tool", "arguments", "mode"})
            if unknown:
                raise ValueError(
                    f"tool request {index + 1} has unexpected fields: {', '.join(unknown)}"
                )
            request_id = raw.get("id")
            tool_name = raw.get("tool")
            arguments = raw.get("arguments")
            mode = raw.get("mode")
            if not isinstance(request_id, str) or not request_id.strip():
                raise ValueError(f"tool request {index + 1} requires a nonempty id")
            if request_id in seen_ids:
                raise ValueError(f"duplicate tool request id: {request_id}")
            seen_ids.add(request_id)
            if not isinstance(tool_name, str) or tool_name not in grants:
                raise ValueError(f"tool is not allowed in this agent request: {tool_name!r}")
            if not isinstance(arguments, Mapping):
                raise TypeError(f"tool request {request_id!r} arguments must be an object")
            if mode not in {"await", "detach"}:
                raise ValueError(f"tool request {request_id!r} has invalid mode: {mode!r}")
            if mode == "detach" and tool_name not in detachable:
                raise ValueError(
                    f"tool request {request_id!r} may not detach {tool_name!r}"
                )
            registration = grants[tool_name]
            tool = record_from_data(
                registration.tool_type,
                dict(arguments),
                reject_unknown=True,
            )
            assert isinstance(tool, PythonTool)
            decoded.append((request_id, registration, tool, mode))
        return decoded

    def _detach_python_tool(
        self,
        registration: ToolRegistration,
        tool: PythonTool[Any],
    ) -> None:
        process = subprocess.Popen(
            [sys.executable, "-m", "agentic_tools.runner", registration.reference],
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            text=True,
            start_new_session=True,
            close_fds=True,
        )
        assert process.stdin is not None
        try:
            process.stdin.write(json.dumps(tool_record_data(tool), ensure_ascii=False))
            process.stdin.close()
        except BaseException:
            process.terminate()
            raise
        self._detached_tool_processes = [
            item for item in self._detached_tool_processes if item.poll() is None
        ]
        self._detached_tool_processes.append(process)

    def _execute_tool_requests(
        self,
        requests: list[tuple[str, ToolRegistration, PythonTool[Any], str]],
    ) -> list[dict[str, object]]:
        results: list[dict[str, object]] = []
        awaited: list[tuple[str, ToolRegistration, PythonTool[Any], Job[Any]]] = []
        for request_id, registration, tool, mode in requests:
            if mode == "detach":
                try:
                    self._detach_python_tool(registration, tool)
                except BaseException as error:
                    results.append(
                        {
                            "id": request_id,
                            "tool": registration.name,
                            "status": "failed",
                            "error": f"{type(error).__name__}: {error}",
                        }
                    )
                else:
                    results.append(
                        {
                            "id": request_id,
                            "tool": registration.name,
                            "status": "accepted",
                        }
                    )
                continue
            awaited.append(
                (
                    request_id,
                    registration,
                    tool,
                    self.launch(tool, agent_visibility="hidden"),
                )
            )

        for request_id, registration, tool, job in awaited:
            try:
                result = self.wait(job)
            except BaseException as error:
                results.append(
                    {
                        "id": request_id,
                        "tool": registration.name,
                        "status": "failed",
                        "error": f"{type(error).__name__}: {error}",
                    }
                )
            else:
                results.append(
                    {
                        "id": request_id,
                        "tool": registration.name,
                        "status": "completed",
                        "result": tool_record_data(tool.agent_observation(result)),
                    }
                )
        return results

    def _complete_agent_request(
        self,
        spec: AgentRequestSpec,
        grants: Mapping[str, ToolRegistration],
        detachable: set[str],
    ) -> Mapping[str, object]:
        validation_error: str | None = None
        tool_results: list[dict[str, object]] | None = None
        while True:
            payload = self._agent_request_payload(
                spec,
                grants,
                detachable,
                validation_error=validation_error,
                tool_results=tool_results,
            )
            response = self.bridge.exchange("agent_request", payload)
            if response.get("kind") == "tool_requests":
                if not grants:
                    validation_error = "this agent request does not allow PythonTools"
                    tool_results = None
                    continue
                try:
                    requests = self._decode_tool_requests(response, grants, detachable)
                except (TypeError, ValueError) as error:
                    validation_error = str(error)
                    tool_results = None
                    continue
                tool_results = self._execute_tool_requests(requests)
                validation_error = None
                continue
            if response.get("kind") == "assignments":
                assignments = response.get("assignments")
            else:
                assignments = response.get("assignments", response)
            if not isinstance(assignments, Mapping):
                validation_error = "resume payload must be an assignments object"
                tool_results = None
                continue
            try:
                _variables, returned = decode_assignments(spec, assignments)
            except (TypeError, ValueError) as error:
                validation_error = str(error)
                tool_results = None
                continue
            return returned

    def agent_request(
        self,
        request_type: type[AgentRequest],
        *,
        name: str | None = None,
        tools: Sequence[type[PythonTool[Any]]] = (),
        detachable_tools: Sequence[type[PythonTool[Any]]] = (),
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
        grants, detachable = self._tool_grants(tools, detachable_tools)
        returned = self._complete_agent_request(spec, grants, detachable)
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
        self.executor: CallbackOperationExecutor | None = None

    def start(self) -> dict[str, object]:
        self.thread.start()
        return self.bridge.events.get()

    def resume(self, payload: Mapping[str, object]) -> dict[str, object]:
        self.bridge.responses.put(dict(payload))
        return self.bridge.events.get()

    def reset_agent_context(self, event: Mapping[str, object]) -> dict[str, object]:
        executor = self.executor
        if executor is None:
            raise OperationExecutionError("callback workflow executor is not ready")
        return executor.reset_agent_context(event)

    def _run(self) -> None:
        try:
            with CallbackOperationExecutor(self.bridge) as executor:
                self.executor = executor
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
