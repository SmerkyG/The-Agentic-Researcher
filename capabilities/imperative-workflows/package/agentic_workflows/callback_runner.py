"""JSON CLI callbacks for a persistent imperative agent-workflow worker."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import time
from typing import Mapping, Sequence
import uuid

from agentic_workflows.callback_runtime import WorkflowThread
from agentic_workflows.contract import AgentWorkflow
from agentic_workflows.execution import OperationExecutionError, record_from_data


def _package_roots() -> tuple[Path, ...]:
    roots: list[Path] = []
    for value in os.environ.get("AR_WORKFLOW_PATH", "").split(os.pathsep):
        if value:
            roots.append(Path(value).resolve())
    own = Path(__file__).resolve().parents[1]
    if own not in roots:
        roots.insert(0, own)
    return tuple(roots)


def _runtime_root() -> Path:
    configured = os.environ.get("AR_RUNTIME_ROOT")
    root = Path(configured) if configured else Path.cwd() / ".runtime"
    return root.resolve() / "workflow-callbacks"


def _utc_now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


def _response_timeout_seconds() -> float:
    raw = os.environ.get("AR_WORKFLOW_CALLBACK_TIMEOUT_SECONDS", "3600")
    try:
        value = float(raw)
    except ValueError as error:
        raise OperationExecutionError(
            "AR_WORKFLOW_CALLBACK_TIMEOUT_SECONDS must be a positive number"
        ) from error
    if value <= 0:
        raise OperationExecutionError(
            "AR_WORKFLOW_CALLBACK_TIMEOUT_SECONDS must be a positive number"
        )
    return value


def _read_json_stdin() -> dict[str, object]:
    text = sys.stdin.read()
    if not text.strip():
        return {}
    value = json.loads(text)
    if not isinstance(value, dict):
        raise OperationExecutionError("callback stdin must be one JSON object")
    return value


def _state_path(run_id: str) -> Path:
    allowed = "abcdefghijklmnopqrstuvwxyz0123456789-"
    if not run_id or any(character not in allowed for character in run_id):
        raise OperationExecutionError("invalid callback run id")
    return _runtime_root() / run_id / "state.json"


def _write_state(path: Path, value: Mapping[str, object]) -> None:
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(dict(value), sort_keys=True), encoding="utf-8")
    os.chmod(temporary, 0o600)
    temporary.replace(path)


def _read_state(run_id: str) -> dict[str, object]:
    path = _state_path(run_id)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError) as error:
        raise OperationExecutionError(f"callback run is unavailable: {run_id}") from error
    if not isinstance(value, dict):
        raise OperationExecutionError(f"invalid callback state: {run_id}")
    return value


def _request(state: Mapping[str, object], message: Mapping[str, object]) -> dict[str, object]:
    port = state.get("port")
    token = state.get("token")
    if not isinstance(port, int) or not isinstance(token, str):
        raise OperationExecutionError("callback worker has invalid connection state")
    payload = {"token": token, **message}
    with socket.create_connection(("127.0.0.1", port), timeout=30) as connection:
        connection.settimeout(_response_timeout_seconds())
        stream = connection.makefile("rwb")
        stream.write(json.dumps(payload, separators=(",", ":")).encode("utf-8") + b"\n")
        stream.flush()
        line = stream.readline()
    if not line:
        raise OperationExecutionError("callback worker closed without a response")
    value = json.loads(line)
    if not isinstance(value, dict):
        raise OperationExecutionError("callback worker returned a non-object response")
    return value


def _attach_control(event: dict[str, object], run_id: str) -> dict[str, object]:
    event = dict(event)
    event["run_id"] = run_id
    boundary_id = event.get("boundary_id")
    if isinstance(boundary_id, str):
        event["resume"] = {
            "command": f"imperative-workflows-callback resume {run_id} {boundary_id}",
            "stdin": "one JSON object",
        }
    return event


def start(implementation: str, inputs: Mapping[str, object]) -> dict[str, object]:
    root = _runtime_root()
    root.mkdir(parents=True, exist_ok=True)
    os.chmod(root, 0o700)
    run_id = uuid.uuid4().hex
    run_dir = root / run_id
    run_dir.mkdir(mode=0o700)
    token = secrets.token_urlsafe(32)
    state_path = run_dir / "state.json"
    log_path = run_dir / "worker.log"

    env = os.environ.copy()
    import_paths = [str(path) for path in sys.path if path]
    existing = env.get("PYTHONPATH")
    if existing:
        import_paths.extend(item for item in existing.split(os.pathsep) if item)
    env["PYTHONPATH"] = os.pathsep.join(dict.fromkeys(import_paths))
    env["AR_CALLBACK_TOKEN"] = token
    with log_path.open("ab", buffering=0) as log:
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "agentic_workflows.callback_runner",
                "_serve",
                run_id,
                implementation,
            ],
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=log,
            env=env,
            start_new_session=True,
        )

    deadline = time.monotonic() + 15
    while not state_path.exists():
        if process.poll() is not None:
            detail = log_path.read_text(encoding="utf-8", errors="replace")
            raise OperationExecutionError(
                "callback worker failed to start: " + detail.strip()
            )
        if time.monotonic() >= deadline:
            process.terminate()
            raise OperationExecutionError("timed out starting callback worker")
        time.sleep(0.05)
    state = _read_state(run_id)
    return _request(state, {"action": "start", "inputs": dict(inputs)})


def resume(run_id: str, boundary_id: str, payload: Mapping[str, object]) -> dict[str, object]:
    return _request(
        _read_state(run_id),
        {
            "action": "resume",
            "boundary_id": boundary_id,
            "payload": dict(payload),
        },
    )


def cancel(run_id: str) -> dict[str, object]:
    return _request(_read_state(run_id), {"action": "cancel"})


def status(run_id: str) -> dict[str, object]:
    """Return public worker state without connection credentials."""

    state = _read_state(run_id)
    public = {key: value for key, value in state.items() if key != "token"}
    pid = public.get("pid")
    if isinstance(pid, int):
        try:
            os.kill(pid, 0)
        except OSError:
            public["process_alive"] = False
        else:
            public["process_alive"] = True
    return public


def _load_workflow(implementation: str, inputs: Mapping[str, object]) -> AgentWorkflow[object]:
    from workflow_source import load_agent_implementation

    workflow_type = load_agent_implementation(
        implementation,
        package_roots=_package_roots(),
    )
    if not issubclass(workflow_type, AgentWorkflow):
        raise OperationExecutionError(f"not an AgentWorkflow: {implementation}")
    workflow = record_from_data(workflow_type, dict(inputs), reject_unknown=True)
    assert isinstance(workflow, AgentWorkflow)
    return workflow


def serve(run_id: str, implementation: str) -> int:
    token = os.environ.get("AR_CALLBACK_TOKEN")
    if not token:
        raise OperationExecutionError("callback worker token is missing")
    state_path = _state_path(run_id)
    state_path.parent.mkdir(parents=True, exist_ok=True)

    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(("127.0.0.1", 0))
    listener.listen(4)
    port = listener.getsockname()[1]
    created_at = _utc_now()
    worker_state: dict[str, object] = {
        "run_id": run_id,
        "implementation": implementation,
        "pid": os.getpid(),
        "port": port,
        "token": token,
        "state": "ready",
        "phase": "waiting_start",
        "pending_boundary": None,
        "pending_event": None,
        "last_event_status": None,
        "last_error": None,
        "created_at": created_at,
        "updated_at": created_at,
    }

    def update_state(**changes: object) -> None:
        worker_state.update(changes)
        worker_state["updated_at"] = _utc_now()
        _write_state(state_path, worker_state)

    update_state()

    workflow_thread: WorkflowThread | None = None
    pending_boundary: str | None = None
    while True:
        connection, _address = listener.accept()
        should_exit = False
        with connection:
            stream = connection.makefile("rwb")
            try:
                message = json.loads(stream.readline())
                if not isinstance(message, dict) or message.get("token") != token:
                    raise OperationExecutionError("callback authentication failed")
                action = message.get("action")
                if action == "start":
                    if workflow_thread is not None:
                        raise OperationExecutionError("callback workflow was already started")
                    inputs = message.get("inputs", {})
                    if not isinstance(inputs, dict):
                        raise OperationExecutionError("workflow inputs must be an object")
                    update_state(
                        state="running",
                        phase="executing",
                        pending_event=None,
                        last_action="start",
                        action_started_at=_utc_now(),
                    )
                    workflow_thread = WorkflowThread(_load_workflow(implementation, inputs))
                    event = workflow_thread.start()
                elif action == "resume":
                    if workflow_thread is None:
                        raise OperationExecutionError("callback workflow has not started")
                    boundary_id = message.get("boundary_id")
                    if boundary_id != pending_boundary:
                        raise OperationExecutionError(
                            f"expected boundary {pending_boundary!r}, got {boundary_id!r}"
                        )
                    payload = message.get("payload", {})
                    if not isinstance(payload, dict):
                        raise OperationExecutionError("resume payload must be an object")
                    update_state(
                        state="running",
                        phase="executing",
                        pending_event=None,
                        last_action="resume",
                        action_started_at=_utc_now(),
                    )
                    event = workflow_thread.resume(payload)
                elif action == "cancel":
                    event = {"status": "cancelled", "boundary_id": None}
                    should_exit = True
                else:
                    raise OperationExecutionError(f"unknown callback action: {action!r}")
                event = _attach_control(event, run_id)
                pending = event.get("boundary_id")
                pending_boundary = pending if isinstance(pending, str) else None
                event_status = event.get("status")
                if event_status in {"complete", "failed", "cancelled"}:
                    should_exit = True
                    update_state(
                        state="finished",
                        phase="finished",
                        pending_boundary=None,
                        pending_event=event,
                        last_event_status=event_status,
                        last_error=event.get("error"),
                    )
                else:
                    update_state(
                        state="ready",
                        phase="waiting_resume",
                        pending_boundary=pending_boundary,
                        pending_event=event,
                        last_event_status=event_status,
                        last_error=None,
                    )
                stream.write(json.dumps(event, separators=(",", ":")).encode("utf-8") + b"\n")
            except Exception as error:
                response = _attach_control(
                    {
                        "status": "request_error",
                        "boundary_id": pending_boundary,
                        "error": f"{type(error).__name__}: {error}",
                    },
                    run_id,
                )
                update_state(
                    state="ready",
                    phase="waiting_resume" if pending_boundary is not None else "waiting_start",
                    pending_boundary=pending_boundary,
                    last_event_status="request_error",
                    last_error=response["error"],
                )
                stream.write(json.dumps(response, separators=(",", ":")).encode("utf-8") + b"\n")
            stream.flush()
        if should_exit:
            break

    update_state(state="finished", phase="finished", pending_boundary=None)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    start_parser = commands.add_parser("start")
    start_parser.add_argument("implementation")
    resume_parser = commands.add_parser("resume")
    resume_parser.add_argument("run_id")
    resume_parser.add_argument("boundary_id")
    cancel_parser = commands.add_parser("cancel")
    cancel_parser.add_argument("run_id")
    status_parser = commands.add_parser("status")
    status_parser.add_argument("run_id")
    serve_parser = commands.add_parser("_serve")
    serve_parser.add_argument("run_id")
    serve_parser.add_argument("implementation")
    return parser


def cli(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "start":
            event = start(args.implementation, _read_json_stdin())
        elif args.command == "resume":
            event = resume(args.run_id, args.boundary_id, _read_json_stdin())
        elif args.command == "cancel":
            event = cancel(args.run_id)
        elif args.command == "status":
            event = status(args.run_id)
        else:
            return serve(args.run_id, args.implementation)
        print(json.dumps(event, sort_keys=True))
        return 0 if event.get("status") not in {"failed", "request_error"} else 1
    except (
        OSError,
        json.JSONDecodeError,
        OperationExecutionError,
        RuntimeError,
        TypeError,
        ValueError,
    ) as error:
        print(
            json.dumps(
                {
                    "status": "failed",
                    "boundary_id": None,
                    "error": f"{type(error).__name__}: {error}",
                },
                sort_keys=True,
            )
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(cli())
