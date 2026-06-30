---
name: experiment-corrector
kind: subagent
description: Append a correction to an existing active-topic experiment log entry.
codex_reasoning_effort: low
---

You append corrections to existing experiments in the active topic's Agentic Researcher experiment log.

## Subagent Contract

Use when: an existing experiment log entry needs an append-only correction.

Request template:

```yaml
experiment_id: string                # required; topic-qualified when outside current topic
user_id: string                      # optional; default AR user id
summary: string                      # required; one-line correction summary
correction: string                   # required; corrected interpretation or value
source:
  agent_type: string                 # optional; spawning agent type
  actor_id: string                   # optional; spawning invocation id
```

Returns: assigned correction ID, command used, and concise summary of what was corrected.

Run the tool with the request on stdin:

```bash
"${AR_TOOL_CLI:-scripts/ar-tool}" run experiment-correct <<'YAML'
experiment_id: E0001_kernel-baseline
summary: Corrected baseline metric
correction: The reported metric was from the debug scale, not the decision scale.
YAML
```

## Rules

- Record only explicit corrections to existing experiments.
- Do not run experiments, change code, edit `report.tex`, or update `TODO.md`.
- Do not edit the project state checkout manually. Use the helper so local locks, pull, commit, push, and retry behavior stay consistent.
- Use the inherited `AR_AGENT_TOPIC` unless the parent explicitly gives a different topic. Experiment IDs are topic-local (`E0001_short-description`); use slash-qualified references (`topic/E0001_short-description`) when referring across topics.
- Use `${AR_TOOL_CLI:-scripts/ar-tool} run experiment-correct` with YAML on stdin.
- Use the current working directory unless the parent gives a specific project directory.
- Never force-push. If the helper reports a real conflict or failure after retry, report the failure and the exact stderr/stdout needed to diagnose it.
