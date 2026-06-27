---
name: "setup_research_plan"
description: "Set up or resume a research project in this workspace."
---

You are a research agent. This skill sets up and executes a research project.
If the user supplied extra text alongside the skill invocation, use it to bootstrap the setup questions and skip questions already answered by that text.

Set `$PROJECT_DIR` to `/workspace` if that directory exists; otherwise set it to the current working directory.

Detect which instruction file exists in the workspace and use it throughout:
- Check for: `CLAUDE.md`, `GEMINI.md`, `AGENTS.md` (in that order)
- Use the first one found as `$INSTRUCTION_FILE`
- If none exists, choose the target from `$AR_CLI_TOOL`: `GEMINI.md` for Gemini; `AGENTS.md` for OpenCode, Codex, or pi; otherwise `CLAUDE.md`.
- If no instruction file exists, stop and ask the user to relaunch Agentic Researcher so the launcher can render it.

Find the Agentic Notes helper:
- Prefer `$AR_NOTES_CLI`.
- Otherwise, if available, use `scripts/ar-notes` from the current repo.
- If no helper is available, stop and ask the user to relaunch Agentic Researcher so project agent-type notes can be updated in shared state.

Set `$MAIN_AGENT` to `${AR_MAIN_AGENT:-research-coordinator}`.

Check the project agent-type notes for `$MAIN_AGENT` to determine what to do:
- Read `$PROJECT_DIR/$INSTRUCTION_FILE` and inspect the generated Agentic Notes section.
- If a `Project Agent Notes: $MAIN_AGENT` injected section is present, treat that text as the agent-type-specific project instructions for this main agent.
- The injected project agent-type note is a materialized view of `.agentic/agent-notes/$MAIN_AGENT/always-injected.md` on the project `agentic/state` branch. Do not edit the rendered section directly.

**Detection logic:**
- If the project agent-type note for `$MAIN_AGENT` contains filled-in values (not just placeholders like `[Research objective]`), treat as **RESUME**.
- If the project agent-type note is missing or still has placeholders, treat as **FRESH START** (skip to interactive setup below).
- If no instruction file exists, stop and ask the user to relaunch Agentic Researcher.

## RESUME (project agent-type note filled):

This is a resuming session. The project is already in progress.

1. **Read** `$PROJECT_DIR/$INSTRUCTION_FILE`, especially the injected `Project Agent Notes: $MAIN_AGENT` section.
2. If the Agentic Researcher experiment log is available, read its `SUMMARY.md` first and open individual experiment YAML files only when needed.
3. Read `report.tex` if present for branch-local narrative analysis, derivations, and detailed results.
4. Read `TODO.md` if present for branch-local open questions and deferred checks. Do not treat it as a shared multi-agent work queue unless the user has provided a separate coordination mechanism.
5. **Run** `git log --oneline -20` to see recent experiment commits
6. **Run** `git status` to check for uncommitted changes
7. **Summarize** the current state to the user:
   - Best result so far and which experiment achieved it
   - What was tried last and whether it worked
   - What's next (from TODO.md, report.tex, or the last logged experiment's next steps)
8. **Ask** the user if they want to continue the planned direction or pivot
9. **Continue** the autonomous experiment loop

## FRESH START (project agent-type note missing or placeholder-only):

1. **Read** `$PROJECT_DIR/$INSTRUCTION_FILE` to confirm project agent-type notes for `$MAIN_AGENT` are missing or placeholder-only.
2. If report.tex exists but the project agent-type note is missing or placeholder-only, read report.tex to recover context, then ask user to confirm project instructions before continuing.
3. Otherwise, proceed with interactive setup below.

### Interactive Setup

Guide the user through filling in project instructions for the selected main agent. Use any extra user text that accompanied the skill invocation to bootstrap Round 1 -- skip questions already answered by that text.

#### Round 1 -- Goal & Context
Ask (2-3 questions max):
- What is your **research goal**? What are you trying to improve? (skip if clear from `$ARGUMENTS`)
- What is the **primary metric**? (e.g., perplexity, accuracy, F1, BLEU -- and which direction is better?)
- What is the **current state of the codebase**? (already have training/eval code, or starting from scratch?)

Wait for the user to respond before continuing.

#### Round 2 -- Evaluation & Constraints
Ask (2-3 questions max):
- What is the **evaluation command**? (e.g., `uv run python evaluate.py --split test`)
- What is the **current baseline performance**? (if known)
- Are there **fixed constraints**? (e.g., model size, quantization bits, max training time, specific architecture that must be used)
- What is your **target improvement**? (e.g., "reduce perplexity by 10%", "beat 95% accuracy")

Wait for the user to respond before continuing.

#### Round 3 -- Approach, Scope & Model Size
Ask (2-3 questions max):
- Any **specific approaches** you want tried? (e.g., "try LoRA", "implement flash attention", "explore curriculum learning")
- Any **papers or references** to follow? (arxiv links, method names)
- What is the **minimum model size for drawing conclusions**? (e.g., ">=1.5B parameters" -- smaller models are debugging-only per Commandment VII)
- Any **files that are off-limits**? (files the agent should NOT modify)
- **Compute budget**: how many experiments / how long can this run? How many GPUs?

Wait for the user to respond before continuing.

#### Round 4 -- Generate & Confirm
1. Draft the project agent-type note for `$MAIN_AGENT` as Markdown from the gathered information:

```markdown
# Research Coordinator Project Instructions

**Goal:** [filled from Round 1]

**Primary Metric:**
- Name: [metric name]
- Direction: [lower/higher is better]
- Eval command: `[exact command]`
- Baseline: [value or "TBD"]

**Fixed Constraints (protected by Commandment II):**
- [from Round 2]

**Minimum Decision Scale (Commandment VII):**
- [from Round 3, e.g., ">=1.5B parameters -- models below this are debugging-only"]

**Approach Guidelines:**
- [from Round 3, ordered by priority]

**References:**
- [papers/links from Round 3]

**Compute Budget:**
- [from Round 3]

**Off-Limits Files:**
- [from Round 3]

**Notes:**
- [any additional context]
```

2. **Show** the filled-in project agent-type note to the user for review
3. **Ask** if they want to modify anything
4. **Save** the approved note to a temporary Markdown file outside the project source tree, then update shared state:

```bash
${AR_NOTES_CLI:-scripts/ar-notes} replace-note \
  --project-dir "$PROJECT_DIR" \
  --scope project \
  --agent-type "$MAIN_AGENT" \
  --note-name always-injected \
  --note-file /tmp/project-agent-type-instructions.md \
  --refresh-parent \
  --tool "${AR_CLI_TOOL:-codex}"
```

This commits the agent-type-specific project instructions to `.agentic/agent-notes/$MAIN_AGENT/always-injected.md` on the project `agentic/state` branch and rematerializes `$PROJECT_DIR/$INSTRUCTION_FILE`. Do not commit the temporary file.
5. **Proceed** with initial setup:
   - **Explore** the codebase structure (`ls -la "$PROJECT_DIR"`, read key files, understand the architecture)
   - **Check GPU** with `nvidia-smi` (note GPU model and VRAM)
   - **Install dependencies** with `uv sync`
   - **Run baseline evaluation**: Execute the evaluation command from the instructions and record results
   - **Initialize tracking files**:
     - `report.tex` with full preamble (amsmath, amsthm, booktabs, graphicx, tcolorbox with verification box, theorem environments), title/date, and a baseline subsection for branch-local narrative analysis
     - `TODO.md` with initial branch-local open questions and deferred checks
     - `mkdir -p scripts images` for verification/plotting scripts and figures
   - **Log baseline**: If the Agentic Researcher experiment log is available, launch the `experiment-logger` subagent with an `experiment_result_request` so the shared summary table receives the assigned experiment ID
   - **Commit**: Commit completed setup/report changes. If an experiment ID was assigned, use it in the commit message.
   - **Begin the autonomous experiment loop** as described in the research workflow
