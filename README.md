# Agentic Team

**Sandboxed Agents That Learn From Their Mistakes Across Agents, Projects, and Teams**

<p align="center">(Forked and rewritten from original repo: The Agentic Researcher)</p>

<p align="center">
  <a href="#problem-statement">Problem Statement</a> &middot;
  <a href="#design-concepts">Design Concepts</a> &middot;
  <a href="#installation">Installation</a> &middot;
  <a href="#workflow">Workflow</a> &middot;
  <a href="#org-repo">Org Repo</a> &middot;
  <a href="#sandbox">Sandbox</a> &middot;
  <a href="#architecture">Architecture</a>
</p>

---

Agentic Team launches AI coding agents that learn from their mistakes and share those learnings with one another, with structured research instructions, workflow guidance, and optional filesystem isolation. The default path uses **sandboxed containers**; `--sandbox none` runs the selected CLI directly on the host without containers or bind mounts. It comes with task workflows for performing Math/ML Research and writing research papers, and supports adding your own new task workflows and custom state management capabilities.

LLM CLIs supported: [Claude Code](https://github.com/anthropics/claude-code), [OpenCode](https://opencode.ai), [Gemini CLI](https://github.com/google-gemini/gemini-cli), [Codex CLI](https://github.com/openai/codex), and [pi](https://github.com/badlogic/pi-mono). Sandboxing optionally supported via Docker, Podman, or Apptainer. Cluster job-queue support is provided through capability packages, with Slurm capabilities included.

## Problem Statement

Long-running agent teams have a memory problem: agents make mistakes, discover missing knowledge, learn local conventions, and uncover tool or infrastructure gotchas, but those lessons usually disappear with the session or context compaction. The next agent, project, or team repeats the same failure because the learning was not captured in a place other agents can use.

Agentic Team's solution is simple: agents take notes and store them in Git. These are kept in your project repo but separate from your normal code branches at project and work-branch scopes. Org-wide notes live in their own separate Git repo. All of these Git-backed notes are shared across agents, projects, installations, and teams through ordinary Git review and merge workflows. Notes apply to either `all-agents` or a specific agent-type.

There are two note modes. `always-injected.md` notes are short, high-value guidance injected into the agent's startup context. On-demand note topics are listed in the generated instructions but read only when relevant; agents read them through `agentic-notes read-note`, which dynamically combines the organization, project, and work-branch portions for `all-agents` plus the current agent type.

The storage layout is simple enough that you can add or edit note files directly if you wish. Working agents read notes through the rendered view rather than opening raw note storage files and are given commands for creating note updates.

## Design Concepts

Agentic Team is split into a small launcher, a shared Git-backed state substrate, and optional capabilities.

**Launcher.** The `agentic-team` command prepares the selected project worktree, materializes the invocation-specific instruction file (`AGENTS.md`, `CLAUDE.md`, or `GEMINI.md`), renders the selected main agent and subagent definitions, runs enabled capability hooks, sets up PATH/env/binds, and then launches the selected LLM CLI in the selected sandbox. The launcher owns CLI and sandbox integration, instruction materialization, branch-ownership prompts, and capability selection. It does not own the schemas for notes or experiment logs.

**Agentic State.** Agentic State is the shared storage substrate used by capabilities. It resolves project identity, manages cached Git checkouts under `$AR_STATE_ROOT`, serializes local state updates with scope-specific locks, and performs ordinary Git fetch/merge/commit/push operations. Organization scope lives in the optional org repo. Project scope lives on the project repo's orphan `agentic/project-state` branch. Work-branch scope lives on one orphan `agentic/work-state/<work-branch>` branch per work branch. Agentic State provides the storage mechanics; capabilities decide what files and schemas they store there.

**Capabilities.** Capabilities are selected packages that can add commands, instruction sections, launcher hooks, and stateful workflows. Built-in capabilities include:

- **Agentic Notes** (`agentic-notes`): owns `agent-notes/` layout at org, project, and work-branch scopes; renders `always-injected.md` content and on-demand note topic lists; provides the `agentic-notes` command with `read-note`, `update-note`, and `rewrite-note` subcommands.
- **Experiment Log** (`experiment-log`): owns `experiment-log/` files on the active work state branch; records experiment YAML files, `COUNTER.yaml`, and append-maintained `SUMMARY.md`; provides the `experiment-log` command with `append`, `correct`, and `summary` subcommands.

This separation is intentional: the launcher can stay mostly about launching and rendering, Agentic State can stay about Git-backed state mechanics, and each capability can evolve its own command surface and data model.

## Prerequisites

- You use **Git** for your projects
- **Docker** (default), **Podman**, or **Apptainer** (Linux only) for sandboxed mode, or a host-installed LLM CLI for `--sandbox none`
- An API key or OAuth login for your chosen CLI (see [supported CLIs](#supported-clis))
- GPU drivers installed on the host if you want GPU passthrough
- Project dependencies managed with [uv](https://docs.astral.sh/uv/) (recommended) — the agent runs `uv sync` inside the sandbox

## Installation

```bash
# 1. Install the launcher
./scripts/install.sh

# 2. Configure local defaults
agentic-team --setup
```

The installer adds the `agentic-team` launcher. The setup wizard creates local configuration, asks whether to use an org repo, and asks which main agent to use. Keep the default `research-coordinator` unless the Agentic Team install or org repo provides another `kind: main` agent. The org repo is optional. Without it, Agentic Team still maintains project state on the project's `agentic/project-state` branch and work-branch-local records on `agentic/work-state/<work-branch>` branches. See [Org Repo](#org-repo) for setup guidance.

## Workflow

### Starting a New Project

1. **Start from a normal project Git checkout.** The checkout should usually have an `origin` remote so Agentic Team can derive the project identity from the repo name automatically.
2. **Run Agentic Team from that checkout:** `cd ~/my-project && agentic-team .`. For auto-approved agent permissions, add `--yolo`.
3. **Use work branches for mutating work.** For example, `git switch -c feature/kernel-search` starts a focused branch, and child branches such as `feature/kernel-search/exp/idea-name` can be used for focused experiments. Agentic Team will help you switch to a useful branch on startup, if necessary.
4. **For a new research effort, ask the default `research-coordinator` main agent to use the `do_research` skill.** This starts an interactive dialogue about your research goal, evaluation metrics, constraints, and compute budget.
5. The agent writes work-branch-specific startup guidance as work-branch Agentic Notes on the work state branch `agentic/work-state/<work-branch>`. Agentic Team renders those notes into the worktree instruction file (`CLAUDE.md`, `GEMINI.md`, or `AGENTS.md`) using the same rules as org and project Agentic Notes. Research workflows may also create capability-owned work-branch files such as `report.tex`, `TODO.md`, and an experiment log on the same work state branch.

If the project has no Git remote, pass `--project-id` or set `AR_PROJECT_ID` so repeated launches use the same notes and experiment state.

### Resuming a Session

Relaunch Agentic Team from the same project Git checkout or another worktree with the same resolved project identity and work branch. The rendered instructions include injected shared notes, active work branch Agentic Notes when present, and any capability-owned work-branch sections for the selected workflow. Use `do_research` on resume only when you want a structured recap or to create/revise research work-branch guidance.

### Multiple Agents in One Project

Agentic Team will detect if you try to run multiple branch-exclusive agents in the same branch, and will ask you to switch or create a new branch to work from. Multiple agents can work on the same project this way via separate branches. Agentic Team also supports multiple agents non-exclusively collaborating on a single branch, but does not provide pre-built workflows for this.

## Sandbox

The default sandbox is Docker when available. If Docker is not installed or not on `PATH`, but Podman is, the launcher and install script automatically fall back to Podman for OCI launches and builds.

In container mode, Agentic Team builds the missing container image automatically on first launch. Use `container/build.sh --runtime docker|podman|apptainer` only when you want to prebuild or rebuild manually. Podman uses the same OCI image and launch flow as Docker, but runs through the `podman` CLI instead. When building with Podman, the build script requests Docker image format (`podman build --format docker`) so Dockerfile `SHELL` directives keep working and Podman avoids noisy OCI-format warnings.

Apptainer is supported on Linux and is the sandbox used for Slurm `remote-run` dispatch. `--sandbox none` skips containers entirely and runs the selected CLI directly in your host environment:

```bash
agentic-team --sandbox none --cli codex ~/my-project
```

`--sandbox none` does not provide Agentic Team filesystem isolation. Install the selected CLI on `PATH` before using it.

## Configuration

Run `agentic-team --setup` to create a configuration file at `${XDG_CONFIG_HOME:-$HOME/.config}/agentic-team/config.sh`. The setup wizard lets you configure:

- **Sandbox** — Docker, Podman, Apptainer, or none host execution
- **CLI** — Claude Code, OpenCode, Gemini CLI, Codex CLI, or pi
- **Authentication** — OAuth login or API key (with configurable env var name)
- **Custom API endpoint** — point Claude at an Anthropic-compatible proxy or gateway
- **Org repo** (`AR_ORG_NOTES_REPO`) — optional shared Git repo for organization-wide notes, agents, and capabilities
- **Main agent** (`AR_MAIN_AGENT`) — top-level agent definition to render into the workspace instruction file. Defaults to `research-coordinator`
- **Work branch** (`AR_WORK_BRANCH` or `--work-branch`) — Git branch used by the top-level agent. Main-agent frontmatter can set `branch_ownership: exclusive|shared|readonly`; the default is `exclusive`
- **Git identity** (`AR_GIT_NAME`, `AR_GIT_EMAIL`) — repo-local fallback identity for Agentic Team-created commits when the project checkout does not already have `user.name` / `user.email`
- **State/cache directory** (`AR_STATE_ROOT`) — where caches, container `/tmp`, and tool state are stored. Defaults to `~/.cache/agentic-team`. On HPC systems with Apptainer, set this to a path with sufficient space (e.g. on a scratch filesystem) to avoid hitting the default 64 MB overlay limit
- **Extra environment variables** (`AR_EXTRA_ENV`) — pipe-separated `KEY=VALUE` pairs forwarded into the container (e.g. `HF_TOKEN=hf_...|WANDB_API_KEY=...`)
- **Network proxy** — HTTP/HTTPS proxy settings for use inside the container
- **Extra bind directories** — additional host paths to mount into the sandbox
- **Auto-build** (`AR_AUTO_BUILD`) — whether missing container images should be built automatically on first launch
- **Capabilities** (`AR_CAPABILITIES`) — comma-separated capability packages from `capabilities/`
- **Project identity override** (`AR_PROJECT_ID` or `--project-id`) — optional stable id for projects without a Git remote, forks that should share state, or other custom grouping
- **Agentic Notes refresh** (`AR_NOTES_REFRESH_MODE`, `AR_NOTES_REFRESH_INTERVAL_SECONDS`) — defaults to periodic background refresh every 120 seconds while at least one agent for the project is running; set mode to `foreground` for synchronous launch refresh or `manual` to disable periodic refresh
- **Startup profiling** (`AR_PROFILE_STARTUP=true`) — print per-phase launcher setup timings to stderr before the selected CLI starts

You can re-run `--setup` at any time to update your configuration.

## Usage

```bash
# Sandbox current directory with Claude Code (default)
agentic-team

# Sandbox a specific project directory
agentic-team ~/my-project

# Use a different CLI
agentic-team --cli gemini

# Run without containers or bind mounts
agentic-team --sandbox none --cli codex

# Materialize AGENTS.md/CLAUDE.md/GEMINI.md and managed subagent files without launching a CLI
agentic-team --render-only --cli codex

# Auto-approve all tool calls
agentic-team --yolo

# Override the inferred project identity when needed
agentic-team --project-id my-project-2026 ~/my-project

# Use a different top-level agent for this launch
agentic-team --main-agent research-paper-author ~/my-project

# Interactive Linux-focused systems/tooling development
agentic-team --main-agent systems-developer ~/my-project

# Create or switch to a specific work branch before launch
agentic-team --work-branch feature/kernel-search .
```

### Project Git and Agentic State

Agentic Team uses your normal project Git repository for code work plus separate Git-backed state branches for agent-facing state. The project worktree stays on your normal code branch; Agentic Team never switches it to a state branch.

If the project Git repo has an `origin` remote, Agentic Team derives the project identity from the remote repo name by default. For example, `https://github.com/YourName/abctest` resolves to project id `abctest`. If the project has no Git remote, or if you need a custom grouping, pass `--project-id` or set `AR_PROJECT_ID`.

The main state scopes are:

| Scope | Backing location |
|-------|------------------|
| Org | Optional org repo configured by `AR_ORG_NOTES_REPO` |
| Project | Project repo orphan branch `agentic/project-state` |
| Work branch | Project repo orphan branch `agentic/work-state/<work-branch>` |

State branches start as orphan branches with empty filesets. They contain only state files created by enabled capabilities, such as Agentic Notes, work-branch research records, and experiment logs. They do not contain `AGENTS.md`, `CLAUDE.md`, `GEMINI.md`, or your code tree.

Multiple top-level agents should usually work in separate Git worktrees of the same project repo. Branch-exclusive agents prompt before running on protected or locally occupied branches; shared and readonly branch modes are also supported through main-agent frontmatter. Branch guard files are local-only under `$AR_STATE_ROOT/branch-guards/`; Git remains the real conflict mechanism.

When the top-level agent has a coherent change set ready to commit, it uses `branch-snapshot` plus `branch-commit` directly so checks and commit creation happen from a temporary worktree. When completed work-branch changes should land in a development branch such as `dev` or `main`, use the `branch-integrator` subagent.

For details, see:

- [docs/agentic-state.md](docs/agentic-state.md) for state scopes, orphan branches, cache locations, locks, refresh, and materialized instruction files
- [docs/agentic-notes.md](docs/agentic-notes.md) for `agent-notes/`, always-injected notes, on-demand notes, and note updates
- [docs/experiment-log.md](docs/experiment-log.md) for research experiment IDs, summaries, correction records, and logging flow

### Job Backend Capabilities

Capability packages can be used for job placement and execution backends, and Agentic Team comes with a SLURM capability called `remote-run`.

Capabilities can also provide prompt-only skills under `capabilities/<name>/skills/<skill-name>/SKILL.md`. Enabled or required capability skills are rendered into the selected CLI's project discovery path: `.claude/skills` for Claude, `.gemini/skills` for Gemini, `.opencode/skills` for OpenCode, and `.agents/skills` for Codex/pi. The built-in `research-coordinator` main agent requires the `research-coordinator` capability, which provides the `do_research` and `retro` research workflow skills. Capability `INSTRUCTIONS.md` files are injected into the workspace instruction file when that capability is enabled.

Agent definitions start from neutral Markdown files in Agentic Team's built-in `agents/` directory and optional org repo `agents/` directory. A definition with `kind: main` can be selected with `AR_MAIN_AGENT` and is inserted into the top-level instruction file. Built-in main agents include `research-coordinator` for experiment-driven research and `systems-developer` for interactive Linux-focused systems/tooling development. Main agents can declare `required_capabilities`; the launcher adds those automatically before validating the selected capability set. A definition with `kind: subagent` is rendered into the selected CLI's project agent path: `.claude/agents` for Claude, `.gemini/agents` for Gemini, `.opencode/agents` for OpenCode, and `.codex/agents` for Codex. Built-in subagents include helpers such as `note-updater`, `experiment-logger`, `experiment-corrector`, `code-reviewer`, and `branch-integrator`. The top-level instruction file also gets a compact generated subagent catalog with each subagent's rendered definition path; the agent reads the rendered subagent contract on demand before launching that subagent. Org repo agents render after built-ins, so org agents win on name conflict. Add `codex_reasoning_effort: low|medium|high` to an agent's frontmatter to render Codex `model_reasoning_effort` for that agent where supported. To add agents and agent types, see [docs/extending-agentic-team.md](docs/extending-agentic-team.md#agents-and-agent-types).

```bash
agentic-team --capability cluster-run
cluster-run status
cluster-run --detach --num-gpus 1 --name exp-e005 -- uv run python train.py --exp E005
```

For multi-node Slurm allocations, enable the managed `remote-run` capability. It checks its own requirements, starts the host-side dispatcher, puts the `remote-run` command on the launched agent's PATH, and exposes the backend to the agent:

```bash
get_gpu 2 2                          # Allocate 2 nodes x 2 GPUs
agentic-team --sandbox apptainer --capability remote-run --test
agentic-team --sandbox apptainer --capability remote-run
remote-run --nodes
remote-run htc-gpuXXX --bg -- uv run python train.py --exp E005
```

To add lab- or site-specific backends, create a capability under `capabilities/` and enable it with `--capability`. See [docs/extending-agentic-team.md](docs/extending-agentic-team.md) for the capability layout, custom job backend checklist, and when launcher changes are needed.

## Org Repo

The org repo is optional. Use one when you want notes, custom agents, or custom capabilities to follow a team across multiple projects or Agentic Team installations.

`agentic-team --setup` asks for this repo and stores it as `AR_ORG_NOTES_REPO`. The value can be a Git URL or a local Git repo path. An empty org repo is a valid starting point: Agentic Team will not inject or list org guidance until notes have been added, but agents can add organization-wide notes later through the note-updater flow.

For a starter layout, copy or adapt [examples/org-notes/](examples/org-notes/):

```text
agents/
  data-curator.md          # kind: subagent rendered for every install
  research-paper-author.md # kind: main selectable with AR_MAIN_AGENT
capabilities/
  my-capability/
    skills/
      my-skill/
        SKILL.md           # optional prompt skill rendered when enabled
    bin/
      my-command           # executable placed on PATH when enabled
    lib/
      common.sh            # optional private support code for this capability
    hooks/
      instruction          # optional render/refresh hook executable
agent-notes/
  all-agents/
    always-injected.md    # short organization-wide guidance injected every time
    git.md                # on-demand topic note listed for relevant work
  research-coordinator/
    always-injected.md    # injected for the default main agent
  gpu-kernel-engineer/
    always-injected.md    # injected for that agent type
```

Put only short, high-value guidance in `always-injected.md`. Put longer or situational details in topic notes such as `agent-notes/all-agents/git.md`, `agent-notes/all-agents/slurm.md`, `agent-notes/all-agents/pytorch.md`, or `agent-notes/gpu-kernel-engineer/benchmarking.md`; Agentic Team lists those topics so agents can read the rendered note only when relevant.

Org-provided agents in `agents/*.md` use the same neutral Markdown format as Agentic Team's built-in agents. They are rendered after built-ins, so an org agent with the same `name` as a built-in agent wins. Org-provided capabilities in `capabilities/<capability>/` are resolved before built-in capabilities with the same name. Enabled capabilities may ship prompt skills under `capabilities/<capability>/skills/<skill-name>/SKILL.md`, commands under `capabilities/<capability>/bin/`, private support code under `capabilities/<capability>/lib/`, launcher hooks under `capabilities/<capability>/launcher/`, and instruction hooks under `capabilities/<capability>/hooks/instruction`. Capabilities are selected with `AR_CAPABILITIES` or `--capability`; main agents can list required capabilities so their prompt skills and state/runtime support are always available. `AR_MAIN_AGENT` selects both the top-level main-agent definition and the agent-type-specific notes for that top-level agent. Subagents use their own `name` as the agent type for agent-type notes.

See [docs/agentic-notes.md](docs/agentic-notes.md) for the notes layout and [docs/extending-agentic-team.md](docs/extending-agentic-team.md) for the agent and capability extension points.

## Supported CLIs

| CLI | Instruction file | Model/API | Flag |
|------|-----------------|----------|------|
| [Claude Code](https://github.com/anthropics/claude-code) | `CLAUDE.md` | Anthropic | `--cli claude` (default) |
| [OpenCode](https://opencode.ai) | `AGENTS.md` | Any (LiteLLM) | `--cli opencode` |
| [Gemini CLI](https://github.com/google-gemini/gemini-cli) | `GEMINI.md` | Google | `--cli gemini` |
| [Codex CLI](https://github.com/openai/codex) | `AGENTS.md` | OpenAI | `--cli codex` |
| [pi](https://github.com/badlogic/pi-mono) | `AGENTS.md` | Any | `--cli pi` |

At launch, Agentic Team also renders a project-local compaction hook for the selected CLI. After context compaction, the hook runs the configured capabilities, refreshes shared Agentic State under local locks, rematerializes the capability sections in the instruction file rendered for that exact invocation (`CLAUDE.md`, `GEMINI.md`, or `AGENTS.md`), tells the continuing model that it has just experienced context compaction, treats that moment as the new "since the last compaction" boundary, asks it to read the refreshed instruction file, and then resumes the task it was already doing. In container mode the Agentic Team install is mounted read-only at `/opt/agentic-team`, while `AR_STATE_ROOT` is mounted read-write so the org checkout, project state branch, and active work state branch can be updated. Claude and Codex use compact-session hooks, Gemini uses `PreCompress` plus a one-shot `BeforeModel` refresh, OpenCode uses a compaction plugin, and pi uses a launch-specific extension.

## Architecture

### Sandbox

| Layer | Details |
|-------|---------|
| **Filesystem isolation** | The agent can write `/workspace` and the mounted `AR_STATE_ROOT`; the Agentic Team install is mounted read-only at `/opt/agentic-team`; extra directories from `AR_EXTRA_BIND_DIRS` are mounted under `/workspace/.mount/<basename>` |
| **Namespace isolation** | Apptainer `--compat` enables user/mount namespaces |
| **Path traversal protection** | Symlinks resolved; system directories blocked |

`--yolo` auto-approves tool calls but does **not** weaken filesystem isolation.

`--sandbox none` intentionally disables Agentic Team filesystem isolation: the selected CLI runs directly in the project directory with your host `HOME`, `PATH`, and credentials.

### Research Agent Instructions

The framework ships `INSTRUCTIONS.md` as a shared base template, capability-owned `instruction-modules/*.md` files as reusable instruction modules, and `agents/*.md` as neutral main-agent and subagent definitions. Agent files can include a capability module with `<!-- AT_INSTRUCTION_MODULE: capability-name/module-name -->`; the launcher expands that directive when it materializes the selected CLI's instruction file or subagent definition.

### Agentic State

Agentic State is implemented as shared command-library code used by capabilities and launcher refresh paths. It owns project identity, state checkout locations, branch naming, local locks, and Git synchronization; capabilities own the files and schemas stored there. See [docs/agentic-state.md](docs/agentic-state.md) for scopes, orphan branches, cache locations, refresh behavior, and materialized instruction files.

### Capabilities

Capabilities own optional commands, structured actions, launcher hooks, and stateful instruction sections. Built-in capabilities live in `capabilities/`:

- `agentic-notes` owns the `agent-notes/` data model, initializes and refreshes org/project/work-branch note state from its launcher hooks, renders Agentic Notes guidance plus dynamic always-injected and on-demand note listings, provides `agentic-notes read-note`, `agentic-notes update-note`, and `agentic-notes rewrite-note`, and runs the background notes refresh loop.
- `experiment-log` owns the active work-branch `experiment-log/` data model, renders active experiment-log guidance, and provides `experiment-log append`, `experiment-log correct`, and `experiment-log summary`. The experiment log is capability-owned and may be absent until the workflow records an experiment.

The default capability list is `agentic-notes,experiment-log` via `AR_CAPABILITIES`. The `capability-refresh` command refreshes configured capability instruction hooks and rematerializes the instruction file for the current invocation after context compaction.

## Citation

Citation for the original Agentic Researcher paper:

```bibtex
@misc{zimmer2026agenticresearcherpracticalguide,
  title         = {The Agentic Researcher: A Practical Guide to AI-Assisted Research
                   in Mathematics and Machine Learning},
  author        = {Max Zimmer and Nico Pelleriti and Christophe Roux and Sebastian Pokutta},
  year          = {2026},
  eprint        = {2603.15914},
  archivePrefix = {arXiv},
  primaryClass  = {cs.LG},
  url           = {https://arxiv.org/abs/2603.15914}
}
```

## License

This project is licensed under the [MIT License](LICENSE).

## Disclaimer

The sandboxing provided by this framework is designed to limit the agent's filesystem access, but it comes with **no guarantee of security**. The authors assume no responsibility for any damage, data loss, or unintended behavior resulting from the use of this software. Use at your own risk.
