# Extending Agentic Team

Agentic Team has two main extension surfaces:

- `agents/` for portable main-agent and subagent definitions.
- `capabilities/` for selected packages that can contribute commands, launcher hooks, instruction hooks, model-facing skills, and startup instructions.

The org repo can use the same `agents/` and `capabilities/` layout. Org definitions win over built-ins with the same name, and org capabilities win over built-in capabilities with the same name.

## Capability Packages

A capability is one selected package. It may contain any combination of these parts:

```text
  capabilities/<name>/
  instruction-modules/    # optional reusable Markdown included by agents
    module-name.md
  skills/                  # optional model-facing skills rendered into CLI skill dirs
    skill-name/
      SKILL.md
  INSTRUCTIONS.md          # optional startup guidance appended to AGENTS/CLAUDE/GEMINI
  bin/                     # optional agent-facing commands added to PATH when enabled
    <name>
    <name>-subcommand
  lib/                     # optional private support code for bin/hooks/launcher scripts
    common.sh
  hooks/
    setup                  # optional instruction/state lifecycle hook
    render-instruction
    post-compaction
  launcher/                # optional sourced launcher hooks
    preflight.sh
    setup.sh
    test.sh
    start.sh
    cleanup.sh
```

Enable capabilities with:

```bash
agentic-team --capability remote-run
```

Or configure the complete enabled list:

```bash
agentic-team --setup AR_CAPABILITIES=agentic-notes,experiment-log,remote-run
```

The default capability list is `agentic-notes,experiment-log`.

Capabilities can be as small as a single prompt skill or as broad as a runtime
integration. A main agent that needs capability-provided skills should list that
capability in its `required_capabilities` frontmatter. For example, the built-in
`research-coordinator` main agent requires the `research-coordinator` capability,
which contributes the `do_research` and `retro` skills.

### `skills/`

Use `skills/<skill-name>/SKILL.md` for prompt routines rendered into the selected
CLI's project skill directory. Agentic Team does not maintain a global always-on
skill directory; skills are available only when their containing capability is
enabled or required by the selected agent.

```text
capabilities/research-coordinator/skills/do_research/SKILL.md
capabilities/research-coordinator/skills/retro/SKILL.md
```

### `bin/`

Use `bin/` for commands the agent should run directly. Every command basename
must be either exactly the capability name or start with `<capability-name>-`.
Put helper scripts and shared code in `lib/`. For small command families,
prefer one eponymous command with subcommands; split into multiple prefixed
commands only when that is clearer:

```text
capabilities/remote-run/bin/remote-run
capabilities/example/bin/example-lint
```

When `remote-run` is enabled, the launched agent can run:

```bash
remote-run --status
remote-run node1 --bg -- uv run python train.py
```

Structured actions use the same `bin/` directory:

```bash
experiment-log append <<'YAML'
summary: ...
YAML
```

Commands are added to `PATH` in this order:

1. enabled capability `capabilities/<capability>/bin/`
2. built-in core commands in `scripts/bin/`

When an org capability and a built-in capability have the same name, the org
capability root is used.

Use `lib/` for private support code used by that capability's own commands and
hooks. The launcher does not add capability `lib/` directories to `PATH`; command
entrypoints should load private helpers relative to their own location.

### `instruction-modules/`

Use `instruction-modules/<module-name>.md` for reusable Markdown that an agent
definition can include by capability-qualified name:

```markdown
<!-- AT_INSTRUCTION_MODULE: research-coordinator/research-ten-commandments -->
```

Modules are resolved from the selected capability root, so org capabilities can
override built-in capability modules by overriding the whole capability.

### `hooks/`

Use `hooks/` when a capability owns rendered or refreshed instruction state.
Each lifecycle hook is its own executable file; missing hooks are treated as
no-ops:

```text
hooks/setup
hooks/render-instruction
hooks/render-section
hooks/render-sections
hooks/post-compaction
hooks/refresh-loop
hooks/cleanup
```

The launcher passes common context through environment variables:

```text
AT_PROJECT_DIR
AT_BRANCH
AT_SESSION_ID
AT_AGENT_TYPE
AT_WORK_BRANCH
AT_CLI
AT_OUTPUT_DIR
AT_HEARTBEAT_DIR
AT_REFRESH_INTERVAL_SECONDS
AT_STALE_SECONDS
```

`hooks/render-sections` receives the agent types to render as positional
arguments and writes to `AT_OUTPUT_DIR`. The built-in `agentic-notes`
capability uses lifecycle hooks to refresh and render Agentic Notes. The
built-in `experiment-log` capability only needs `hooks/render-instruction` to
render work-branch experiment-log guidance.

### `launcher/`

Use `launcher/` when a capability needs runtime integration before the agent starts. These scripts are sourced by the launcher, so they may share variables and append to launcher arrays.

```text
launcher/
  preflight.sh  # validate host/sandbox requirements
  setup.sh      # add binds/env after storage setup
  test.sh       # handle --test
  start.sh      # start host daemons before CLI launch
  cleanup.sh    # stop daemons on launcher exit
```

`setup.sh` may append Apptainer bind arguments to `CAPABILITY_BINDS` and runtime env arguments to `CAPABILITY_ENV`.

`remote-run` uses this pattern to validate Apptainer plus Slurm, create a dispatch directory, start the dispatcher daemon, and expose dispatch environment to the launched agent.

## Agents and Agent Types

Agent definitions are neutral Markdown files with frontmatter:

```markdown
---
name: data-curator
kind: subagent
description: Inspect datasets, manifests, splits, and preprocessing for research experiments.
codex_reasoning_effort: medium
required_capabilities:
  - agentic-notes
---

# Data Curator

...
```

- `kind: main` definitions are selectable with `AR_MAIN_AGENT`.
- `kind: subagent` definitions are rendered into the selected CLI's project subagent directory.
- `description` should be short and action-oriented.
- `codex_reasoning_effort` is optional and rendered only for Codex-compatible configs.
- Main agents can declare required capabilities with `required_capabilities:`. The launcher adds these to the selected capability set automatically before validation.

Subagents should have exactly one `## Subagent Contract` section with one request template. If a workflow needs a different request shape, create another subagent.

## Org Repo Layout

An org repo can provide portable extensions:

```text
agents/
  research-paper-author.md
  data-curator.md
capabilities/
  lab-slurm/
    INSTRUCTIONS.md
    skills/
      lab-slurm/
        SKILL.md
    bin/
      lab-slurm
    lib/
      common.sh
    launcher/
      preflight.sh
      setup.sh
agent-notes/
  all-agents/
    always-injected.md
    slurm.md
```

Org capabilities are resolved before built-in capabilities with the same name.

## Authoring Checklist

- Give each capability one clear purpose.
- Put agent-facing commands and YAML-based structured actions in `bin/`.
- Put private shared implementation code for those commands in capability-local `lib/`.
- Put launcher/runtime integration in `launcher/`.
- Put rendered/refreshed instruction state in lifecycle executables under `hooks/`.
- Keep `INSTRUCTIONS.md` short; put longer situational knowledge in Agentic Notes.
- Prefer subagents for workflows requiring model judgment and commands for executable actions.
