# Extending Agentic Team

Agentic Team extensions are capability packages. A capability can provide main
agents, subagents, tools, skills, Python workflow modules, rendering behavior,
launcher hooks, and startup instructions. Selecting a main agent automatically
enables the capability that provides it.

Capabilities may come from the project, configured organization repo, or
Agentic Team installation. A project capability replaces an org or built-in
capability with the same name; an org capability replaces the built-in one.

## Capability Packages

A capability is one selected package. It may contain any combination of these parts:

```text
  capabilities/<name>/
  capability.toml        # optional metadata and capability dependencies
  agents/                 # optional main-agent and subagent definitions
    agent-name.md
  package/                # optional Python workflow contracts and operations
    python-package/
  instruction-modules/    # optional reusable Markdown included by agents
    module-name.md
  skills/                  # optional model-facing skills rendered into CLI skill dirs
    skill-name/
      SKILL.md
  INSTRUCTIONS.md          # optional startup guidance appended to AGENTS/CLAUDE/GEMINI
  bin/                     # optional agent-facing commands added to PATH when enabled
    <name>
    <name>-subcommand
  lib/                     # optional private support code for bin/hooks/render/launcher code
    common.sh
  render.py                # optional Python instruction renderer
  hooks/
    setup                  # optional instruction/state lifecycle hook
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

The default capability list is `agentic-notes,experiment-log`. In addition, the
launcher enables the capability providing the selected main agent and follows
the transitive `requires` list from each enabled capability's
`capability.toml`:

```toml
description = "Provide a research workflow."
requires = ["imperative-workflows", "agentic-notes", "experiment-log"]
```

Capabilities can be as small as a single prompt skill or as broad as a complete
agent implementation. The built-in `research-coordinator` capability provides
the coordinator, its subagents, the `do_research` and `retro` skills, and its
research-state commands.

Project capabilities live at
`<project>/.agentic-team/capabilities/<name>/`. Choosing an agent exported by a
project capability or explicitly enabling that capability allows its prompts,
renderers, hooks, and commands to run. Review project capability code with the
same care as other project automation.

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

Provider precedence is project, then organization, then built-in. A higher
precedence capability replaces the lower provider as one unit.

Use `lib/` for private support code used by that capability's own commands,
hooks, renderer, and launcher scripts. The launcher does not add capability
`lib/` directories to `PATH`; command entrypoints should load private helpers
relative to their own location.

### `render.py`

Use `render.py` for capability-owned instruction rendering. Render-related
capability extension points are Python-only; executable lifecycle hooks are not
used for rendering. A render module may define any of these functions:

```python
def render_instruction(ctx) -> str: ...
def render_agent_section(ctx, agent_type: str) -> str: ...
def render_agent_sections(ctx, agent_types: list[str]) -> dict[str, str]: ...
def render_source(ctx, source_path, source_kind: str) -> str: ...
```

`ctx` provides:

```text
project_dir
agent_type
work_branch
cli
repo_root
state_root
capability_name
capability_root
capability_roots
```

`render_source` transforms an agent or skill source that names the capability in
its `renderer:` frontmatter. `render_instruction` appends content to the main rendered instruction file.
`render_agent_section` appends capability-owned content to one rendered
subagent definition. `render_agent_sections` is an optional batch fast path for
rendering sections for many subagents at once. Missing functions are treated as
no-ops. The renderer adds the capability root and its `lib/` directory to
`sys.path` while loading `render.py`, so private Python helpers can live in
that capability's `lib/` directory.

### `instruction-modules/`

Use `instruction-modules/<module-name>.md` for reusable Markdown that an agent
definition can include by capability-qualified name:

```markdown
<!-- AT_INSTRUCTION_MODULE: research-coordinator/research-ten-commandments -->
```

Modules are resolved from the selected capability root, so org capabilities can
override built-in capability modules by overriding the whole capability.

### Imperative workflows

The optional `imperative-workflows` capability is a source renderer. A provider
that uses it lists it in `capability.toml`; plain Markdown agent capabilities do
not need it. Modular workflows keep public invocation contracts and reusable
operations in ordinary Python, while agent Markdown keeps launcher metadata,
declarative guidance, and one implementation block:

```text
capabilities/<provider>/
  package/<python-package>/     public contracts and operations
  agents/                       agent guidance and workflow implementations
  skills/                       on-demand skill definitions
```

An agent definition declares the interface and implementation pairing in
frontmatter:

```yaml
renderer: imperative-workflows
workflow_interface: agentic_workflows.research.finalizer:ResearchFinalizer
workflow_module: agentic_workflows.research.workflows.finalizer
workflow_entry: ResearchFinalizerWorkflow
```

Its body contains exactly one tagged block:

````markdown
```python agentic-workflow
from agentic_workflows.research.finalizer import ResearchFinalizer

class ResearchFinalizerWorkflow(ResearchFinalizer):
    def workflow(self) -> None:
        ...
```
````

The renderer combines `package/` roots from enabled capabilities. It indexes
Python modules below those roots, indexes tagged agent and skill modules,
and walks local imports from both the public interface and implementation. The
rendered agent therefore receives the complete implementation graph, while a
caller that imports only the public class does not receive the called agent's
implementation module. Workflow metadata is stripped from platform-specific
agent files.

Dependency inclusion is module-level, not symbol-level. Keep modules aligned
with operation ownership so a workflow sees only the capabilities it uses. In
particular, separate read, mutation, and worker-only operations when different
agents own them instead of collecting them in one convenience module.

A modular skill uses the same tagged block but extends the current agent
context instead of declaring a separately dispatched agent:

```yaml
renderer: imperative-workflows
workflow_receiver: agentic_workflows.research.research_coordinator:ResearchCoordinator
workflow_module: agentic_workflows.research.do_research
workflow_entry: do_research
```

Its entry is an ordinary function whose first parameter is annotated with the
receiver class:

```python
def do_research(self: ResearchCoordinator) -> None:
    ...
```

The launcher validates that annotation, walks imports from the receiver and
skill module, preserves normal skill discovery fields such as `name` and
`description`, and strips the `workflow_*` metadata from the installed
`SKILL.md`. Plain Markdown skills remain valid.

### `hooks/`

Use `hooks/` when a capability owns refreshed instruction state or other
launcher lifecycle work.
Each lifecycle hook is its own executable file; missing hooks are treated as
no-ops:

```text
hooks/setup
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

The built-in `agentic-notes` capability uses lifecycle hooks to initialize and
refresh Agentic Notes. It uses `render.py` to render Agentic Notes guidance,
always-injected notes, and on-demand note listings. The built-in
`experiment-log` capability uses `render.py` to render work-branch
experiment-log guidance.

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

Agent definitions are neutral Markdown files under a capability's `agents/`
directory:

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
- Selecting a main agent enables its providing capability. Put shared dependencies in the provider's `capability.toml`; `required_capabilities:` remains available for agent-specific additions.

Subagents should have exactly one `## Subagent Contract` section with one request template. If a workflow needs a different request shape, create another subagent.

## Org And Project Layout

An org repo can provide portable extensions:

```text
  capabilities/
    research-paper/
      capability.toml
      agents/
        research-paper-author.md
        data-curator.md
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

An org repo uses `capabilities/` at its root. A project uses the same layout
below `.agentic-team/capabilities/`. Project providers win over org providers,
which win over built-ins.

## Authoring Checklist

- Give each capability one clear purpose.
- Put agent-facing commands and YAML-based structured actions in `bin/`.
- Put private shared implementation code for those commands in capability-local `lib/`.
- Put launcher/runtime integration in `launcher/`.
- Put rendered/refreshed instruction state in lifecycle executables under `hooks/`.
- Keep `INSTRUCTIONS.md` short; put longer situational knowledge in Agentic Notes.
- Prefer subagents for workflows requiring model judgment and commands for executable actions.
