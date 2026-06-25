# Extending Agentic Researcher

Agentic Researcher can be extended without changing the core launcher by adding skills, optional skills, and subagents.

Use:

- `skills/` for always-on project skills that should be rendered for every launch.
- `optional-skills/` for selectable capabilities such as GPU job backends, cluster tools, site-specific data systems, or lab-specific workflows.
- `agents/` for subagents that should be rendered into the selected CLI's subagent directory.

This page focuses on optional skills because they are the usual extension point for custom GPU job backends.

## Optional Skill Layout

Create one directory per optional skill:

```text
optional-skills/
  my-gpu-backend/
    SKILL.md
    INSTRUCTIONS.md
```

`SKILL.md` is the model-facing skill. It should have frontmatter:

```markdown
---
name: "my-gpu-backend"
description: "Place and manage GPU jobs with the my-gpu-backend command."
---

# My GPU Backend

Use `my-gpu-backend` for independent GPU experiments when this optional skill is active.
```

`INSTRUCTIONS.md` is optional. If present, AR appends it to the workspace instruction file inside a managed block. Use it for short launch-wide guidance that should be visible even before the model opens the skill.

An optional skill directory must contain at least one of `SKILL.md` or `INSTRUCTIONS.md`.

## Activation

Enable an optional skill for one launch:

```bash
agentic-researcher --project-id my-project-2026 --optional-skill my-gpu-backend .
```

Enable one or more optional skills through config:

```bash
agentic-researcher --setup AR_OPTIONAL_SKILLS=my-gpu-backend,site-data
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

Generated skill and instruction files are runtime artifacts and should remain ignored in project code branches.

## Custom GPU Job Backends

An optional skill can support a custom GPU backend by teaching the agent:

- how to discover capacity
- how to submit one independent experiment per GPU
- how to run jobs in the background
- how to monitor logs and status
- how to cancel stuck jobs
- which environment variables or mount paths the backend exports
- when not to dispatch work, especially dependent multi-step jobs

A useful GPU backend optional skill usually includes exact command examples.

Start each work batch by checking backend capacity:

```bash
my-gpu-backend status
my-gpu-backend status --verbose
```

Submit long experiments detached:

```bash
my-gpu-backend submit --gpus 1 --name exp-e005 -- uv run python train.py --exp E005
```

Monitor and cancel:

```bash
my-gpu-backend logs JOB_ID
my-gpu-backend logs --follow JOB_ID
my-gpu-backend cancel JOB_ID
```

Keep the skill operational and concrete. Prefer exact commands over high-level descriptions.

## What Optional Skills Do Not Install

Optional skills provide instructions to the model. They do not install backend commands, credentials, Python packages, SSH configuration, cluster CLIs, or cloud tools.

For native mode, the backend command must be available on the host `PATH` before launch.

For container mode, the backend command must be available inside the container or reachable through configured mounts and environment variables. Common options are:

- bake the command into the AR container image
- expose a host-side wrapper through `AR_EXTRA_BIND_DIRS`
- pass required tokens or endpoints through `AR_EXTRA_ENV`
- use an existing command already installed in the container

Document those requirements in the optional skill and in any site-local README.

## Built-In GPU Backend Integration

AR currently has first-class launcher handling for:

- `cluster-run`
- `remote-run`

Those can be selected through `--gpu-backend` or automatically by launcher logic. Custom backends do not need first-class launcher support if `--optional-skill my-gpu-backend` is enough.

If you want a custom backend to be selected through `--gpu-backend my-backend`, update the launcher in addition to adding the optional skill:

- accept the backend name in `parse_arguments`
- allow it in `resolve_gpu_backend`
- add validation in `validate_gpu_backend`
- append the matching optional skill in `resolve_optional_skills`
- pass any required environment variables or binds

Keep first-class launcher integration small. Most backend-specific behavior belongs in the backend command and the optional skill docs.

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
agentic-researcher --project-id test-project --optional-skill my-gpu-backend --native --tool codex /path/to/project
```

Then confirm the rendered skill appears under the selected CLI's project skill directory and the instruction overlay appears in the workspace instruction file.
