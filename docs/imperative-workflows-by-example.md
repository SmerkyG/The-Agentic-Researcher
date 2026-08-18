# Imperative Workflows by Example

Python executes the workflow. The LLM sees only explicit agent, user, and
subagent boundaries, plus visible operation results queued for the next agent
request. The JSON below is abbreviated to emphasize the model-visible part.

## One aggregate agent request

```python
class ChooseWork(AgentRequest):
    with guidance("Prefer the smallest decisive check."):
        experiment: str = local("next experiment")
        command: str = local(f"command that tests {experiment}")
    step(f"Run {command} and inspect its output.")
    conclusion: str = result(
        f"conclusion supported by the result of {experiment}",
        guidance="Report negative results honestly.",
    )

choice = self.agent_request(ChooseWork)
print(choice.conclusion)       # returned to Python
# choice.experiment            # invalid: local values remain agent-only
```

The LLM sees one request, in declaration order:

```text
Process agent request `ChooseWork`:
1. Process this guided scope:
   1.1. Assign context-local value `experiment` (str):
        next experiment
   1.2. Assign context-local value `command` (str):
        command that tests `experiment`
   Guidance for this scope:
     Prefer the smallest decisive check.
2. Perform these actions in order:
   1. Run `command` and inspect its output.
3. Assign returned result `conclusion` (str):
   conclusion supported by the result of `experiment`
   Guidance for this assignment:
     Report negative results honestly.

After all steps have genuinely completed, return one JSON object with
exactly these assignments: experiment, command, conclusion.
```

It returns all assignments for validation:

```json
{
  "assignments": {
    "experiment": "compare both parsers",
    "command": "uv run pytest tests/test_parser.py",
    "conclusion": "The new parser is equivalent on the focused cases."
  }
}
```

Only `result()` values become attributes on `choice`. `local()` values remain
available to later nodes in the same request. Formatting either declaration in
an f-string emits its backticked identifier; it does not read a Python value.

## Python values and queued observations

Concrete Python values may be interpolated normally:

```python
records_dir = workspace.records_dir

class ReadState(AgentRequest):
    step(f"Read the report under {records_dir}.")
    summary: str = result("summary of the report")
```

Use an observation when the LLM should receive a complete external or derived
value rather than merely its string representation:

```python
status = inspect_status()
self.queue_agent_observation(status, desc="current worker status")
answer = self.agent_request(ReadState)
```

The next request starts with:

```text
External observations queued for this request:
Observation 1 (Status) — current worker status
  {
    "state": "ready",
    "pending": 2
  }
```

The observation is consumed exactly once.

## Operations

```python
summary = SummaryTool(branch="main").run()
SecretAuditTool().run(agent_visibility="hidden")

first = self.launch(BuildTool(target="a"))
second = self.launch(BuildTool(target="b"))
results = self.wait_all([first, second])
```

These calls execute in Python and do not interrupt the LLM. By default, each
top-level operation queues an observation for the next agent request:

```json
{
  "operation": "example.tools:SummaryTool",
  "action": "Summarize one branch.",
  "inputs": {"branch": "main"},
  "status": "completed",
  "result": {"commits": 4}
}
```

An asynchronous operation first has status `launched`; after `wait()`,
`wait_all()`, or `wait_any()` its queued observation is replaced by
`completed`. `cancel(job)` requests cancellation. `agent_visibility="hidden"`
suppresses the observation. The current callback runtime supports detached
`fire_and_forget()` for subagents, shown below; it rejects detached ordinary
operations unless the tool itself owns a durable background launch.

An `ExecutableWorkflow` behaves as one operation: its internal operations are
not shown separately. The LLM sees only the outer operation observation.

## Agent-callable Python tools

Tools are granted to one request, not globally:

```python
review = self.agent_request(
    Review,
    tools=[ReadArtifactTool, RefreshIndexTool],
    detachable_tools=[RefreshIndexTool],
)
```

The request includes the current grant and definitions that are new or changed:

```json
{
  "available_tools": [
    {"name": "read_artifact", "modes": ["await"]},
    {"name": "refresh_index", "modes": ["await", "detach"]}
  ],
  "tool_definitions": {
    "read_artifact": {
      "name": "read_artifact",
      "description": "Read one artifact.",
      "input_schema": {"type": "object", "properties": {"path": {"type": "string"}}}
    }
  }
}
```

Instead of final assignments, the LLM may first return:

```json
{
  "kind": "tool_requests",
  "requests": [
    {
      "id": "read-1",
      "tool": "read_artifact",
      "arguments": {"path": "results.json"},
      "mode": "await"
    },
    {
      "id": "refresh-1",
      "tool": "refresh_index",
      "arguments": {},
      "mode": "detach"
    }
  ]
}
```

The executor runs independent requests, then resumes the same agent request:

```json
{
  "tool_results": [
    {"id": "read-1", "tool": "read_artifact", "status": "completed", "result": {"rows": 12}},
    {"id": "refresh-1", "tool": "refresh_index", "status": "accepted"}
  ]
}
```

The LLM may request more tools or return its assignments. Detached results are
not available to that request. Known definitions are referenced by name on
later requests and resent after context compaction.

## User and subagent boundaries

```python
answer = self.ask_user(
    "Ask which baseline should be authoritative and explain why it matters."
)
```

The LLM receives an `ask_user` boundary containing that instruction, formulates
the visible question, and Python resumes with the user's answer.

```python
result = ResearchFinalizer(ticket=ticket).run()  # launch child and wait

job = self.admit(ResearchFinalizer(ticket=ticket))
self.detach(job)                                 # accepted handoff; do not wait

self.fire_and_forget(ResearchFinalizer(ticket=ticket))
# Equivalent accepted handoff followed by detach.
```

A synchronous child produces a `subagent_run` boundary:

```json
{
  "agent_name": "research-finalizer",
  "inputs": {"ticket": {"id": "F-42"}},
  "instructions": "Run the named `research-finalizer` subagent ... and wait for its typed result."
}
```

`admit()` instead produces `subagent_admission` and resumes Python only after
the launcher accepts the child. `detach()` then transfers lifecycle ownership
to the launcher. A `SubagentWorkflow` body always runs in the child, never in
the caller's Python worker or agent context.

## Ordinary Python and lifecycle methods

```python
def on_startup(self) -> None:
    self.load_state()

def on_compaction(self) -> None:
    self.load_state()

def workflow(self) -> None:
    for item in items:
        if item.enabled:
            ProcessTool(item=item).run()
```

Loops, branches, assignments, function calls, and returns execute as ordinary
Python and emit no prose to the LLM. `on_startup()` runs before `workflow()`;
`on_compaction()` refreshes state before the interrupted boundary resumes. Only
an operation configured as shown, `queue_agent_observation()`,
`agent_request()`, `ask_user()`, or a native subagent boundary changes what the
LLM sees.
