# Extending Agentic Researcher

Agentic Researcher can be extended without changing the core launcher by adding skills, optional skills, main agents, subagents, and agent-facing tools.

Use:

- `skills/` for always-on project skills that should be rendered for every launch.
- `optional-skills/` for selectable capabilities such as job backends, cluster tools, site-specific data systems, or lab-specific workflows.
- AR install `agents/` for built-in main agents and subagents.
- Org repo `agents/` for organization-provided main agents and subagents shared across AR installations.
- Org repo `agent-tools/` for organization-provided executable tools callable through `ar-tool run`.

This page covers optional skills, agents, and agent-facing tools. Optional skills are the usual extension point for custom job backends; agents are the extension point for top-level workflows and reusable delegation agent types; tools are the extension point for concrete executable actions those agents can call.

## Agents and Agent Types

AR ships neutral agent definitions in its built-in `agents/` directory. If `AR_ORG_NOTES_REPO` is configured, the org repo may also provide neutral agent definitions in its own `agents/` directory. Each definition declares whether it is a top-level main agent or a rendered subagent:

- `kind: main` definitions are selectable with `AR_MAIN_AGENT` and are inserted into the workspace instruction file (`CLAUDE.md`, `GEMINI.md`, or `AGENTS.md`). The default main agent is `research-coordinator`.
- `kind: subagent` definitions are rendered into the selected CLI's project subagent directory:

| Tool | Rendered subagent directory |
|------|-----------------------------|
| Claude | `.claude/agents/` |
| Gemini | `.gemini/agents/` |
| OpenCode | `.opencode/agents/` |
| Codex | `.codex/agents/` |

To add a managed agent for one AR installation, create a Markdown file in the AR install's `agents/` directory. To share the same agent across every AR installation configured with the same org repo, create it in the org repo's `agents/` directory instead:

```text
agents/
  data-curator.md
  research-paper-author.md
```

Subagent example:

```markdown
---
name: data-curator
kind: subagent
description: Inspect datasets, manifests, splits, and preprocessing for research experiments.
codex_reasoning_effort: medium
---

You are a data curation agent for Agentic Researcher projects.

Responsibilities:

- Check dataset manifests and split definitions before experiments use them.
- Identify leakage, duplicate examples, missing labels, and preprocessing drift.
- Summarize risks and exact files inspected.

Return:

- Dataset or split checked
- Problems found
- Commands or files used for verification
- Recommended fixes
```

Main-agent example:

```markdown
---
name: research-paper-author
kind: main
description: Draft and revise research-paper text from verified project evidence.
codex_reasoning_effort: high
---

# Research Paper Author Instructions

You are a top-level paper-authoring agent for an Agentic Researcher project.
Read the project instructions, experiment summary, relevant reports, figures,
and verified references before drafting. Treat experiment logs and cited sources
as evidence; do not invent results, metrics, citations, or claims.
```

`name` is the stable agent id. For `kind: main`, it is the value used in `AR_MAIN_AGENT`. For `kind: subagent`, it is the id the working agent will use when launching the subagent. The same name also doubles as the agent type for agent-type notes. For example, a subagent named `data-curator` will receive agent-type notes from:

```text
agent-notes/
  data-curator/
    always-injected.md
    data-quality.md
```

The default top-level agent, `research-coordinator`, receives agent-type notes from:

```text
agent-notes/
  research-coordinator/
    always-injected.md
    planning.md
```

`description` should be short and action-oriented because CLIs use it to decide when a subagent is relevant and because humans use it to choose main agents. `kind` is required. `codex_reasoning_effort` is optional and is rendered only for Codex-compatible configs; use `low`, `medium`, or `high`.

Precedence is intentional: AR loads built-in agents first and org repo agents second. If an org repo agent has the same `name` as a built-in AR agent, the org repo version wins. This applies across kinds: an org `kind: main` definition with the same name as a built-in `kind: subagent` prevents the built-in subagent from being rendered.

Unmanaged project-local CLI-specific agent files are still protected; AR skips them instead of overwriting them.

Keep subagents narrow. If a capability is mostly an executable action, make it an agent tool; if it is mostly model-facing guidance for an existing backend command, make it an optional skill. If it is a recurring delegated workflow with its own responsibilities and output shape, make it a subagent, like built-in `branch-committer` for background topic commits or built-in `branch-integrator` for landing completed topic work into a development branch. Each subagent should have exactly one typed request template in a `## Subagent Contract` section; create another subagent when a workflow needs another request shape. Use main agents for top-level operating modes, such as built-in `research-coordinator` for experiment-driven research, built-in `systems-developer` for interactive Linux-focused systems/tooling development, or an org-provided `research-paper-author`.

Current limitation: AR renders all final `kind: subagent` definitions for every launch. There is not yet an `optional-agents/` selector. Project-local CLI-specific subagent files may still work for a specific CLI, and AR will not overwrite unmanaged files at the same rendered path, but those files are not portable across CLIs and do not get AR's neutral rendering behavior.

## Agent Tools

Agent tools are executable commands called through:

```bash
"${AR_TOOL_CLI:-scripts/ar-tool}" run tool-name <<'YAML'
field: value
YAML
```

The model supplies YAML on stdin. It should not be asked to write temporary request files; tools can handle any internal files they need.

Built-in tools live in the AR install under `scripts/tools/`. To share a site-specific tool across AR installations, add an executable to the org notes repo:

```text
agent-tools/
  my-tool/
    bin/
      my-tool
```

Org tools win over built-in tools with the same name. Keep each tool narrow and give it one input shape. If a workflow needs model judgment, status reporting, or delegation policy, describe that workflow in a subagent and have the subagent call the tool. If it is only model-facing instructions for an existing backend command, an optional skill may be enough.

## Optional Skill Layout

Create one directory per optional skill:

```text
optional-skills/
  my-job-backend/
    SKILL.md
    INSTRUCTIONS.md
```

`SKILL.md` is the model-facing skill. It should have frontmatter:

```markdown
---
name: "my-job-backend"
description: "Place and manage jobs with the my-job-backend command."
---

# My Job Backend

Use `my-job-backend` for independent experiments when this optional skill is active.
```

`INSTRUCTIONS.md` is optional. If present, AR appends it to the workspace instruction file inside a managed block. Use it for short launch-wide guidance that should be visible even before the model opens the skill.

An optional skill directory must contain at least one of `SKILL.md` or `INSTRUCTIONS.md`.

## Activation

Enable an optional skill for one launch:

```bash
agentic-researcher --optional-skill my-job-backend .
```

Enable one or more optional skills through config:

```bash
agentic-researcher --setup AR_OPTIONAL_SKILLS=my-job-backend,site-data
```

Optional skill names may contain only letters, numbers, dots, underscores, and hyphens.

When selected, AR renders `SKILL.md` into the selected CLI's project skill directory:

| Tool | Rendered skill directory |
|------|--------------------------|
| Claude | `.claude/skills/` |
| Gemini | `.gemini/skills/` |
| OpenCode | `.opencode/skills/` |
| Codex | `.agents/skills/` |
| pi | `.agents/skills/` |

If `INSTRUCTIONS.md` exists, AR also appends it to the generated workspace instruction file (`CLAUDE.md`, `GEMINI.md`, or `AGENTS.md`).

Generated skill and instruction files are launch artifacts and should remain ignored in project code branches.

## Custom Job Backends

An optional skill can support a custom job backend by teaching the agent:

- how to discover capacity
- how to submit one independent experiment per GPU
- how to run jobs in the background
- how to monitor logs and status
- how to cancel stuck jobs
- which environment variables or mount paths the backend exports
- when not to dispatch work, especially dependent multi-step jobs

A useful job backend optional skill usually includes exact command examples.

Start each work batch by checking backend capacity:

```bash
my-job-backend status
my-job-backend status --verbose
```

Submit long experiments detached:

```bash
my-job-backend submit --gpus 1 --name exp-e005 -- uv run python train.py --exp E005
```

Monitor and cancel:

```bash
my-job-backend logs JOB_ID
my-job-backend logs --follow JOB_ID
my-job-backend cancel JOB_ID
```

Keep the skill operational and concrete. Prefer exact commands over high-level descriptions.

## What Optional Skills Do Not Install

Optional skills provide instructions to the model. They do not install backend commands, credentials, Python packages, SSH configuration, cluster CLIs, or cloud tools.

For `--sandbox none`, the backend command must be available on the host `PATH` before launch.

For container mode, the backend command must be available inside the container or reachable through configured mounts and environment variables. Common options are:

- bake the command into the AR container image
- expose a host-side wrapper through `AR_EXTRA_BIND_DIRS`
- pass required tokens or endpoints through `AR_EXTRA_ENV`
- use an existing command already installed in the container

Document those requirements in the optional skill and in any site-local README.

## Managed Job Backend Hooks

Some optional skills need launcher support beyond model-facing instructions.
For example, `cluster-run` validates the host command before launch, and
`remote-run` starts a Slurm dispatcher before the agent starts.

Managed optional skills can also provide launcher hook scripts under `optional-skills/<name>/launcher/`:

```text
launcher/
  preflight.sh  # sourced before container image setup; validate requirements
  setup.sh      # sourced after launcher storage/mount setup; add binds/env
  test.sh       # sourced for --test when this skill is selected
  start.sh      # sourced before launching the agent; start host daemons
  cleanup.sh    # sourced on launcher exit after start.sh ran
```

The `remote-run` Slurm backend uses this pattern. Its optional skill validates Apptainer and Slurm requirements, starts the dispatcher, binds the `remote-run` command into the sandbox, and implements `--test`.

Launcher hook scripts are sourced by the launcher, so they can share state across phases. `setup.sh` may append Apptainer bind arguments to `OPTIONAL_SKILL_BINDS` and environment arguments to `OPTIONAL_SKILL_ENV`; `cleanup.sh` can use variables set by `start.sh`.

Keep launcher hooks small. Most backend-specific behavior belongs in the
backend command and the optional skill docs.

## Optional Skill Authoring Checklist

- Name the directory exactly as users will pass it to `--optional-skill`.
- Add clear frontmatter to `SKILL.md`.
- Include a short `INSTRUCTIONS.md` when startup instructions are useful.
- Give exact status, submit, log, and cancel commands.
- Explain detached/background execution.
- State which jobs are safe to dispatch.
- State required host/container setup.
- Avoid changing evaluation metrics, datasets, or protected project constraints.
- Test with:

```bash
agentic-researcher --optional-skill my-job-backend --sandbox none --tool codex /path/to/project
```

Then confirm the rendered skill appears under the selected CLI's project skill directory and the instruction overlay appears in the workspace instruction file.
