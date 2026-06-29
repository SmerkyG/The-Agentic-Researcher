# Agentic Team

**Sandboxed Research Agents That Learn From Their Mistakes Across Agents, Projects, and Teams**

<p align="center">(Forked and rewritten from original repo: The Agentic Researcher)</p>

<p align="center">
  <a href="#problem-statement">Problem Statement</a> &middot;
  <a href="#installation">Installation</a> &middot;
  <a href="#workflow">Workflow</a> &middot;
  <a href="#org-notes">Org Notes</a> &middot;
  <a href="#sandbox">Sandbox</a> &middot;
  <a href="#architecture">Architecture</a>
</p>

---

Agentic Team launches AI coding agents that learn from their mistakes and share those learnings with one another, with structured research instructions, workflow guidance, and optional filesystem isolation. The default path uses **sandboxed containers**; `--sandbox none` runs the selected CLI directly on the host without containers or bind mounts. It comes with task workflows for performing Math/ML Research and writing research papers, and supports adding your own new task workflows.

LLM CLIs supported: [Claude Code](https://github.com/anthropics/claude-code), [OpenCode](https://opencode.ai), [Gemini CLI](https://github.com/google-gemini/gemini-cli), [Codex CLI](https://github.com/openai/codex), and [pi](https://github.com/badlogic/pi-mono). Sandboxing optionally supported via Docker, Podman, or Apptainer. Cluster job-queue optionally supported via plugin system, with SLURM plugin provided.

## Problem Statement

Long-running agent teams have a memory problem: agents make mistakes, discover missing knowledge, learn local conventions, and uncover tool or infrastructure gotchas, but those lessons usually disappear with the session or context compaction. The next agent, project, or team repeats the same failure because the learning was not captured in a place other agents can use.

Agentic Team's solution is simple: agents take notes. Org notes live in an org-level Git repo under `agent-notes/all-agents/` and `agent-notes/<agent_type>/`. Project notes live on an orphan `agentic/state` branch under `.agentic/agent-notes/all-agents/` and `.agentic/agent-notes/<agent_type>/`, separate from the normal code branches. Those Git-backed notes are shared across agents, projects, installations, and teams through ordinary Git review and merge workflows.

There are two note modes. `always-injected.md` notes are short, high-value guidance injected into the agent's startup context. On-demand note topics are listed in the generated instructions but read only when relevant; agents read them through `ar-notes read-note`, which dynamically combines the organization/project and all-agents/agent-type portions for the current project and agent type.

The storage layout is simple enough that you can add or edit note files directly if you wish. Working agents should still read notes through the rendered view instead of opening raw note storage files.

## Prerequisites

- **Docker** (default), **Podman**, or **Apptainer** (Linux only) for sandboxed mode, or a host-installed CLI tool for `--sandbox none`
- An API key or OAuth login for your chosen CLI tool (see [supported tools](#supported-cli-tools))
- GPU drivers installed on the host if you want GPU passthrough
- Project dependencies managed with [uv](https://docs.astral.sh/uv/) (recommended) — the agent runs `uv sync` inside the sandbox

## Installation

```bash
# 1. Install the launcher
./scripts/install.sh

# 2. Configure local defaults
agentic-researcher --setup
```

The installer adds the `agentic-researcher` launcher. The setup wizard creates local configuration, asks whether to use an org notes repo, and asks which main agent to use. Keep the default `research-coordinator` unless the AR install or org notes repo provides another `kind: main` agent. Org notes are optional. Without them, AR still maintains project notes and topic-local experiment logs on the project's `agentic/state` branch. See [Org Notes](#org-notes) for the repo layout and when to use it.

## Workflow

### Starting a New Project

1. **Start from a normal project Git checkout.** The checkout should usually have an `origin` remote so AR can derive the project identity from the repo name automatically.
2. **Create or enter a topic branch:** `git switch -c agent/my-topic` for a new topic, or `git switch agent/my-topic` to resume one. Use child branches such as `agent/my-topic/exp/idea-name` for focused experiments.
3. **Run AR from that checkout:** `cd ~/my-project && agentic-researcher .`. AR infers topic `my-topic` from the current `agent/my-topic` branch or any child branch under it. For auto-approved agent permissions, add `--yolo`.
4. **For a new research effort, ask the default `research-coordinator` main agent to use the `setup_research_plan` skill.** This starts an interactive dialogue about your research goal, evaluation metrics, constraints, and compute budget.
5. The agent writes agent-type-specific project instructions to project agent-type notes on the project `agentic/state` branch. AR injects those notes into the worktree instruction file (`CLAUDE.md`, `GEMINI.md`, or `AGENTS.md`) and creates branch-local research files such as `report.tex` and `TODO.md`.

If the project has no Git remote, pass `--project-id` or set `AR_PROJECT_ID` so repeated launches use the same notes and topic state.

### Resuming a Session

Relaunch AR from the same project Git checkout or another worktree with the same resolved project identity and topic branch. The rendered instructions tell the agent to use the injected project agent-type notes, active topic experiment summary, branch-local `report.tex`, and `TODO.md` before continuing. Use `setup_research_plan` on resume only when you want a structured recap or to revise the coordinator project agent-type note.

## Sandbox

The default sandbox is Docker when available. If Docker is not installed or not on `PATH`, but Podman is, the launcher and install script automatically fall back to Podman for OCI launches and builds.

In container mode, AR builds the missing container image automatically on first launch. Use `container/build.sh --runtime docker|podman|apptainer` only when you want to prebuild or rebuild manually. Podman uses the same OCI image and launch flow as Docker, but runs through the `podman` CLI instead. When building with Podman, the build script requests Docker image format (`podman build --format docker`) so Dockerfile `SHELL` directives keep working and Podman avoids noisy OCI-format warnings.

Apptainer is supported on Linux and is the sandbox used for Slurm `remote-run` dispatch. `--sandbox none` skips containers entirely and runs the selected CLI directly in your host environment:

```bash
agentic-researcher --sandbox none --tool codex ~/my-project
```

`--sandbox none` does not provide Agentic Researcher filesystem isolation. Install the selected CLI tool on `PATH` before using it.

## Configuration

Run `agentic-researcher --setup` to create a configuration file at `${XDG_CONFIG_HOME:-$HOME/.config}/agentic-researcher/config.sh`. The setup wizard lets you configure:

- **Sandbox** — Docker, Podman, Apptainer, or none host execution
- **CLI tool** — Claude Code, OpenCode, Gemini CLI, Codex CLI, or pi
- **Authentication** — OAuth login or API key (with configurable env var name)
- **Custom API endpoint** — point Claude at an Anthropic-compatible proxy or gateway
- **Org notes repo** (`AR_ORG_NOTES_REPO`) — optional shared Git repo for organization-wide and agent-type-specific notes
- **Main agent** (`AR_MAIN_AGENT`) — top-level agent definition to render into the workspace instruction file. Defaults to `research-coordinator`
- **Agent topic** (`AR_AGENT_TOPIC` or `--agent-topic`) — work lane for one active top-level agent. AR normally infers this from the current `agent/<topic>` branch. The matching branch must be `agent/<topic>` or a child branch such as `agent/<topic>/exp/<experiment>`
- **State/cache directory** (`AR_STATE_ROOT`) — where caches, container `/tmp`, and tool state are stored. Defaults to `~/.cache/agentic-researcher`. On HPC systems with Apptainer, set this to a path with sufficient space (e.g. on a scratch filesystem) to avoid hitting the default 64 MB overlay limit
- **Extra environment variables** (`AR_EXTRA_ENV`) — pipe-separated `KEY=VALUE` pairs forwarded into the container (e.g. `HF_TOKEN=hf_...|WANDB_API_KEY=...`)
- **Network proxy** — HTTP/HTTPS proxy settings for use inside the container
- **Extra bind directories** — additional host paths to mount into the sandbox
- **Auto-build** (`AR_AUTO_BUILD`) — whether missing container images should be built automatically on first launch
- **Optional skills** (`AR_OPTIONAL_SKILLS`) — comma-separated selectable skills from `optional-skills/`
- **Project identity override** (`AR_PROJECT_ID` or `--project-id`) — optional stable id for projects without a Git remote, forks that should share state, or other custom grouping
- **Agentic Notes refresh** (`AR_NOTES_REFRESH_MODE`, `AR_NOTES_REFRESH_INTERVAL_SECONDS`) — defaults to periodic background refresh every 120 seconds while at least one agent for the project is running; set mode to `foreground` for synchronous launch refresh or `manual` to disable periodic refresh
- **Startup profiling** (`AR_PROFILE_STARTUP=true`) — print per-phase launcher setup timings to stderr before the selected CLI starts

You can re-run `--setup` at any time to update your configuration.

## Usage

```bash
# Sandbox current directory with Claude Code (default)
agentic-researcher

# Sandbox a specific project directory
agentic-researcher ~/my-project

# Use a different CLI tool
agentic-researcher --tool gemini

# Run without containers or bind mounts
agentic-researcher --sandbox none --tool codex

# Auto-approve all tool calls
agentic-researcher --yolo

# Override the inferred project identity when needed
agentic-researcher --project-id my-project-2026 ~/my-project

# Use a different top-level agent for this launch
agentic-researcher --main-agent research-paper-author ~/my-project

# Override the inferred topic only when needed
agentic-researcher --agent-topic my-topic .
```

### Project Git and Agentic Notes State

Agentic Researcher uses your normal project Git repository for code work and a separate Git-backed state branch for learned project notes and experiment logs. The agent's project worktree stays on your normal code branch; AR never switches it to the state branch.

Use AR from an ordinary project worktree. If the project Git repo has an `origin` remote, AR derives the project identity from the remote repo name by default. For example, `https://github.com/SmerkyG/abctest` resolves to project id `abctest`. You can override that identity with `--project-id`, `AR_PROJECT_ID`, or config when the project has no remote, when two unrelated repos share the same repo name, or when you want a custom grouping:

```bash
agentic-researcher .
```

Organization-wide and agent-type-specific notes are optional; configure `AR_ORG_NOTES_REPO` only when you want that shared scope.

On launch, AR creates a cached checkout at `$AR_STATE_ROOT/projects/<project-id>/agentic-state/` if needed and renders instructions from the local cached state. By default, one project-scoped background loop refreshes org and project Agentic Notes every 120 seconds while any agent for that project is running, so multiple agents do not multiply remote Git checks. Note updates still perform synchronous locked refresh/push operations. Experiment logging is locked per topic, so different topics do not block one another.

The project `agentic/state` branch stores:

```text
.agentic/agent-notes/all-agents/always-injected.md
.agentic/agent-notes/<agent_type>/always-injected.md
.agentic/topics/<topic>/ACTIVE.yaml
.agentic/topics/<topic>/experiment-log/COUNTER.yaml
.agentic/topics/<topic>/experiment-log/SUMMARY.md
.agentic/topics/<topic>/experiment-log/experiments/
```

When AR creates `agentic/state` for the first time, it creates an orphan branch with an empty starting fileset and commits only the `.agentic/` state files. It does not copy the current code tree, branch contents, datasets, or generated files into `agentic/state`. If `agentic/state` already exists on the remote, AR checks out and updates that existing state branch instead of recreating it.

If the project has no Git remote, pass `--project-id` or set `AR_PROJECT_ID`. The project state checkout is then local to that AR installation and cannot be shared or pushed unless the project later gets a remote.

Multiple projects are supported within one AR installation. Each project gets a separate cache directory keyed by the resolved project id. AR does not infer project identity from the directory name. For multi-worktree or multi-agent projects, use worktrees whose `origin` remotes have the same repo name, or pass the same `--project-id` or set the same `AR_PROJECT_ID` in every launch so all agents share the same notes and topic state.

Each top-level agent works in one topic at a time. There must be only one active top-level agent per topic; split collaboration into separate topics rather than running multiple top-level agents in one topic. A topic branch is named `agent/<topic>`, with optional child branches such as `agent/<topic>/exp/<experiment-name>`. AR refuses normal launches from `main`, `master`, detached HEAD, or a branch that does not match the selected topic.

Multiple top-level agents should work in separate Git worktrees of the same project repo. Their code branches and materialized instruction files stay independent, while project notes and project agent-type notes are serialized through the shared cached `agentic/state` checkout. Experiment logs are scoped and locked per topic under `.agentic/topics/<topic>/experiment-log/`. Subagents rendered by a top-level launch inherit the same project id, topic, and state checkout as their parent agent.

Example with a coordinator and a paper author sharing one project:

```bash
git worktree add -b agent/kernel-search ../my-project-coordinator main
git worktree add -b agent/paper-draft ../my-project-paper main

agentic-researcher --main-agent research-coordinator ../my-project-coordinator
agentic-researcher --main-agent research-paper-author ../my-project-paper
```

Run the `research-coordinator` project setup flow once to create or revise `.agentic/agent-notes/research-coordinator/always-injected.md`. Other main agents can have their own project agent-type notes; run their setup flow only when that agent type needs agent-type-specific project instructions.

Each worktree gets its own generated `AGENTS.md`, `CLAUDE.md`, or `GEMINI.md` based on the selected main agent. Those files are materialized views and should not be treated as canonical shared state. Shared project guidance for all agents lives in `.agentic/agent-notes/all-agents/always-injected.md`; agent-type-specific project guidance lives in `.agentic/agent-notes/<agent_type>/always-injected.md`.

The `agentic/state` branch does not store `AGENTS.md`, `CLAUDE.md`, or `GEMINI.md`. It stores Agentic Notes, topic leases, and topic-local experiment logs; each worktree rematerializes its own instruction file on launch or refresh.

`report.tex` and `TODO.md` remain normal files in the project worktree. AR does not lock them, so they should be treated as branch-local narrative and checklist files rather than a shared multi-agent queue or canonical experiment index. The durable experiment history is the active topic's locked experiment log on `agentic/state`; a project-wide aggregate can be derived later from topic logs.

See [docs/agentic-notes.md](docs/agentic-notes.md) for the notes repo layout, agent-type notes, note-updater flow, experiment-logger flow, and experiment log format.

### Job Backend Skills

Agentic Researcher can render project skills for job placement and execution backends. Backends are selected explicitly as optional skills.

Skill definitions start from neutral Agentic Researcher sources. Always-on skills live in `skills/`; selectable skills live in `optional-skills/`. Both are rendered into the selected CLI's project discovery path: `.claude/skills` for Claude, `.gemini/skills` for Gemini, `.opencode/skills` for OpenCode, and `.agents/skills` for Codex/pi. If a selected skill has `INSTRUCTIONS.md`, that file is also injected into the workspace instruction file.

Agent definitions start from neutral Markdown files in AR's built-in `agents/` directory and optional org repo `agents/` directory. A definition with `kind: main` can be selected with `AR_MAIN_AGENT` and is inserted into the top-level instruction file. A definition with `kind: subagent` is rendered into the selected CLI's project agent path: `.claude/agents` for Claude, `.gemini/agents` for Gemini, `.opencode/agents` for OpenCode, and `.codex/agents` for Codex. Org repo agents render after built-ins, so org agents win on name conflict. Add `codex_reasoning_effort: low|medium|high` to an agent's frontmatter to render Codex `model_reasoning_effort` for that agent where supported. To add agents and agent types, see [docs/extending-ar.md](docs/extending-ar.md#agents-and-agent-types).

```bash
agentic-researcher --optional-skill cluster-run
cluster-run status
cluster-run --detach --num-gpus 1 --name exp-e005 -- uv run python train.py --exp E005
```

For multi-node Slurm allocations, enable the managed `remote-run` optional skill. It checks its own requirements, starts the host-side dispatcher, binds the `remote-run` command into the Apptainer sandbox, and exposes the backend to the agent:

```bash
get_gpu 2 2                          # Allocate 2 nodes x 2 GPUs
agentic-researcher --sandbox apptainer --optional-skill remote-run --test
agentic-researcher --sandbox apptainer --optional-skill remote-run
remote-run --nodes
remote-run htc-gpuXXX --bg -- uv run python train.py --exp E005
```

To add lab- or site-specific backends, create an optional skill under `optional-skills/` and enable it with `--optional-skill`. See [docs/extending-ar.md](docs/extending-ar.md) for the optional skill layout, custom job backend checklist, and when launcher changes are needed.

## Org Notes

An org notes repo is optional shared memory for guidance and learned lessons that should follow agents across multiple projects or AR installations. Use it for lab-wide conventions, shared infrastructure notes, package gotchas, benchmark rules, agent-type-specific habits, or org-provided main agents and subagents. An empty org notes repo is a valid starting point when you want AR to accumulate organization-wide and agent-type-specific notes over time. It just will not inject or list org/agent-type guidance until notes have been added.

For immediate useful guidance, seed the repo from the example layout in [examples/org-notes/](examples/org-notes/):

```text
agents/
  data-curator.md          # kind: subagent rendered for every install
  research-paper-author.md # kind: main selectable with AR_MAIN_AGENT
agent-notes/
  all-agents/
    always-injected.md    # short organization-wide guidance injected every time
    git.md                # on-demand topic note listed for relevant work
  research-coordinator/
    always-injected.md    # injected for the default main agent
  gpu-kernel-engineer/
    always-injected.md    # injected for that agent type
```

Put only short, high-value guidance in `always-injected.md`. Put longer or situational details in topic notes such as `agent-notes/all-agents/git.md`, `agent-notes/all-agents/slurm.md`, `agent-notes/all-agents/pytorch.md`, or `agent-notes/gpu-kernel-engineer/benchmarking.md`; AR lists those topics so agents can read the rendered note only when relevant.

Org-provided agents in `agents/*.md` use the same neutral Markdown format as AR's built-in agents. They are rendered after built-ins, so an org agent with the same `name` as a built-in agent wins. `AR_MAIN_AGENT` selects both the top-level main-agent definition and the agent-type-specific notes for that top-level agent. Subagents use their own `name` as the agent type for agent-type notes.

See [docs/agentic-notes.md](docs/agentic-notes.md) for the full notes layout and [docs/extending-ar.md](docs/extending-ar.md#agents-and-agent-types) for the agent format.

## Supported CLI Tools

| Tool | Instruction file | Provider | Flag |
|------|-----------------|----------|------|
| [Claude Code](https://github.com/anthropics/claude-code) | `CLAUDE.md` | Anthropic | `--tool claude` (default) |
| [OpenCode](https://opencode.ai) | `AGENTS.md` | Any (LiteLLM) | `--tool opencode` |
| [Gemini CLI](https://github.com/google-gemini/gemini-cli) | `GEMINI.md` | Google | `--tool gemini` |
| [Codex CLI](https://github.com/openai/codex) | `AGENTS.md` | OpenAI | `--tool codex` |
| [pi](https://github.com/badlogic/pi-mono) | `AGENTS.md` | Any | `--tool pi` |

At launch, AR also renders a project-local compaction hook for the selected CLI. After context compaction, the hook uses `$AR_NOTES_CLI` to pull the org notes and project `agentic/state` checkouts under local locks, rematerializes the instruction file rendered for that exact invocation (`CLAUDE.md`, `GEMINI.md`, or `AGENTS.md`), tells the continuing model that it has just experienced context compaction, treats that moment as the new "since the last compaction" boundary, asks it to read the refreshed instruction file, and then resumes the task it was already doing. In container mode the AR install is mounted read-only at `/opt/agentic-researcher`, while `AR_STATE_ROOT` is mounted read-write so the org checkout and project state branch can be updated. Claude and Codex use compact-session hooks, Gemini uses `PreCompress` plus a one-shot `BeforeModel` refresh, OpenCode uses a compaction plugin, and pi uses a launch-specific extension.

## Architecture

### Sandbox

| Layer | Details |
|-------|---------|
| **Filesystem isolation** | The agent can write `/workspace` and the mounted `AR_STATE_ROOT`; the AR install is mounted read-only at `/opt/agentic-researcher`; extra directories from `AR_EXTRA_BIND_DIRS` are mounted under `/workspace/.mount/<basename>` |
| **Namespace isolation** | Apptainer `--compat` enables user/mount namespaces |
| **Path traversal protection** | Symlinks resolved; system directories blocked |

`--yolo` auto-approves tool calls but does **not** weaken filesystem isolation.

`--sandbox none` intentionally disables Agentic Researcher filesystem isolation: the selected CLI runs directly in the project directory with your host `HOME`, `PATH`, and credentials.

### Research Agent Instructions

The framework ships `INSTRUCTIONS.md` as a shared base template and `agents/*.md` as neutral main-agent and subagent definitions. At launch, AR renders the selected main agent and injects matching org/project notes into the workspace under the filename required by the selected tool. The `setup_research_plan` skill updates the `research-coordinator` project agent-type note on `agentic/state`; it does not make the materialized instruction file canonical.

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
