---
name: "do_research"
description: "Set up or resume a research work branch in this workspace."
---

You are a research agent. This skill sets up or resumes the active research
work branch for the current Agentic Team launch. If the user supplied extra text
alongside the skill invocation, use it to bootstrap the setup questions and skip
questions already answered by that text.

Set `$PROJECT_DIR` to `/workspace` if that directory exists; otherwise set it to
the current working directory.

Set:
- `$MAIN_AGENT` to `${AR_MAIN_AGENT:-research-coordinator}`
- `$WORK_BRANCH` to `${AR_WORK_BRANCH:-}`
- `$WORK_STATE_DIR` to `${AR_WORK_STATE_DIR:?}`

If `$WORK_BRANCH` is empty, stop and ask the user to relaunch from a named Git
branch or pass `--work-branch`.

## State Model

Use injected Agentic Notes and project/agent-type `always-injected.md` text as
already-active durable guidance. Do not reopen source `always-injected.md`
files.

The active work branch's durable state lives on the project work state branch
`agentic/work-state/$WORK_BRANCH`:

- `agent-notes/all-agents/` and `agent-notes/$MAIN_AGENT/` are work-branch Agentic
  Notes. They work like org and project Agentic Notes, but apply only to this
  work branch.
- `experiment-log/` is the append-only experiment ledger when the experiment-log
  provider creates it.
- `report.md` is mutable work-branch-local narrative synthesis when this research
  workflow creates it.
- `TODO.md` is the mutable work-branch-local checklist when this research workflow
  creates it.
- `images/` stores report-ready figures referenced by `report.md`.

Code branches and experiment subbranches hold code. Do not treat worktree
`report.md`, worktree `TODO.md`, or worktree report `images/` as canonical
work-branch records.

## Detect Resume vs Fresh Start

Use the Agentic Notes already injected in the current context.

- If filled work-branch always-injected content is present for `$WORK_BRANCH` and
  `$MAIN_AGENT` or `all-agents`, treat this as **RESUME**.
- If the work-branch guidance is missing or placeholder-only, treat this as
  **FRESH START**.

## RESUME

This work branch is already in progress.

1. Use the injected work-branch Agentic Notes as the active plan.
2. Read the active work-branch experiment summary when it exists:

   ```bash
   experiment-log summary --project-dir "$PROJECT_DIR" --work-branch "$WORK_BRANCH" 2>/dev/null || true
   ```

3. Read work-branch `report.md` and `TODO.md` only when needed:

   ```bash
   test -f "$WORK_STATE_DIR/report.md" && sed -n '1,220p' "$WORK_STATE_DIR/report.md"
   test -f "$WORK_STATE_DIR/TODO.md" && sed -n '1,220p' "$WORK_STATE_DIR/TODO.md"
   ```

4. Run `git log --oneline -20` and `git status`.
5. Summarize the current state to the user:
   - Best result so far and which experiment achieved it
   - What was tried last and whether it worked
   - What's next from the active work-branch plan, work-branch TODO, work-branch report, or last
     logged experiment's next steps
6. Ask the user if they want to continue the planned direction or pivot.
7. Continue the autonomous experiment loop. Completing one `TODO.md` item is
   not a stopping condition; after checking off finished items, pick the next
   unchecked item, experiment, or analysis step and keep going unless user input
   is required.
   If you add a next TODO item, begin it immediately unless it is blocked or
   requires user input.

## FRESH START

Create work-branch-specific always-injected guidance for `$WORK_BRANCH`. For the default
research coordinator, this guidance is formatted as a compact research plan.
Write it as a work-branch Agentic Note for `$MAIN_AGENT`, not as a shared project note.

### Interactive Setup

Guide the user through filling in work-branch instructions. Use any extra user text
that accompanied the skill invocation to bootstrap Round 1 and skip questions
already answered by that text.

#### Round 1 -- Goal and Context

Ask 2-3 questions max:
- What is the research goal for this work branch?
- What is the primary metric and which direction is better?
- What is the current state of the codebase?

Wait for the user to respond before continuing.

#### Round 2 -- Evaluation and Constraints

Ask 2-3 questions max:
- What is the exact evaluation command?
- What is the current baseline performance, if known?
- What fixed constraints must not change?
- What target improvement would count as success?

Wait for the user to respond before continuing.

#### Round 3 -- Approach, Scope, and Compute

Ask 2-3 questions max:
- What approaches should be tried first?
- Any papers, references, or prior attempts to follow?
- What is the minimum scale for drawing conclusions?
- Any files or areas that are off limits?
- What compute budget is available?

Wait for the user to respond before continuing.

#### Round 4 -- Generate and Confirm

1. Draft the work-branch research plan as Markdown:

```markdown
# Research Plan: $WORK_BRANCH

**Work Branch:** `$WORK_BRANCH`

**Goal:** [filled from Round 1]

**Primary Metric:**
- Name: [metric name]
- Direction: [lower/higher is better]
- Eval command: `[exact command]`
- Baseline: [value or "TBD"]

**Fixed Constraints:**
- [from Round 2]

**Minimum Decision Scale:**
- [from Round 3, e.g. ">=1.5B parameters -- smaller models are debugging-only"]

**Initial Approach:**
- [from Round 3, ordered by priority]

**References:**
- [papers/links from Round 3]

**Compute Budget:**
- [from Round 3]

**Off-Limits Files or Areas:**
- [from Round 3]

**Current Next Steps:**
- [first concrete actions]

**Notes:**
- [additional context]
```

2. Show the filled-in plan to the user for review.
3. Ask if they want to modify anything.
4. Save the approved plan to `$WORK_STATE_DIR/agent-notes/$MAIN_AGENT/always-injected.md`
   and commit it on the work-state branch. This setup step initializes the
   work-branch plan directly; normal learned note updates still go through the
   `note-updater` subagent. For normal learned note updates, try to spawn
   `note-updater`, retry once if spawning fails, and alert the user if it still
   cannot be spawned instead of silently calling `agentic-notes` directly.

```bash
mkdir -p "$WORK_STATE_DIR/agent-notes/$MAIN_AGENT"
cp /tmp/work-branch-always-injected.md "$WORK_STATE_DIR/agent-notes/$MAIN_AGENT/always-injected.md"
git -C "$WORK_STATE_DIR" add "agent-notes/$MAIN_AGENT/always-injected.md"
git -C "$WORK_STATE_DIR" commit -m "work-state: initialize $WORK_BRANCH research plan"
git -C "$WORK_STATE_DIR" push
```

This commits `agent-notes/$MAIN_AGENT/always-injected.md` on
`agentic/work-state/$WORK_BRANCH`. Do not commit the temporary file.

The approved plan is already in the current conversation because you just
drafted it and the user approved it. Treat it as active immediately. Future
Agentic Team launches, resumes, or compaction refreshes can render the committed
plan into startup instructions for later contexts, but regenerating an
instruction file does not update this already-running model context.

5. Initialize work-branch `report.md` and `TODO.md` in the work-state worktree.
   These are normal files in that worktree, not Agentic Notes commands:

```bash
cat > "$WORK_STATE_DIR/report.md" <<'MARKDOWN'
# Research Log

Use this Markdown notebook for branch-local narrative analysis, derivations,
figures, verification notes, and selected result tables. Embed LaTeX math when
needed, for example `$O(n \log n)$` or display equations.
MARKDOWN

cat > "$WORK_STATE_DIR/TODO.md" <<'MARKDOWN'
# TODO

- [ ] Run baseline evaluation
MARKDOWN

mkdir -p "$WORK_STATE_DIR/images"
git -C "$WORK_STATE_DIR" add report.md TODO.md images/
git -C "$WORK_STATE_DIR" commit -m "work-state: initialize $WORK_BRANCH research records"
git -C "$WORK_STATE_DIR" push
```

Use Markdown headings and tables in `report.md`; embed LaTeX math only when it
helps the derivation. Use Markdown image links for figures, embedding PNGs
such as `![caption](images/name.png)` rather than PDF-only links. Save
report-ready PNG/PDF figures under `$WORK_STATE_DIR/images/` and commit
`images/` with the report even though those files are binary. Keep raw arrays,
checkpoints, full logs, datasets, and other bulky generated artifacts under
`$AR_ARTIFACTS_DIR` instead. Use a unique run or experiment subdirectory for
new artifact writes so parallel AT work does not overwrite shared project
artifacts. Use `TODO.md` checklist items in `- [ ] item` format.

6. Proceed with initial setup:
   - Explore the codebase structure and understand the architecture
   - Check local GPU availability with `nvidia-smi`; if unavailable, try
     `rocm-smi`
   - Install dependencies with `uv sync`
   - Run the baseline evaluation command from the research plan
   - Update work-branch `report.md`, `TODO.md`, and report figures by editing
     the work-state worktree and committing those files there
   - If the baseline is a meaningful completed experiment, launch
     `experiment-logger` so the active work-branch summary receives an
     experiment ID; retry once if spawning fails and alert the user if it still
     cannot be spawned
   - Commit only code/config/script changes that belong in the code branch; do
     not commit work-branch Agentic Notes, `report.md`, `TODO.md`, or report
     `images/` to the code branch
   - Begin the autonomous experiment loop and keep repeating it until no useful
     autonomous work remains

Before any final response after using this skill, inspect the active work-branch
`TODO.md`. If unchecked actionable items remain, continue the experiment loop
instead of reporting completion. Return with unchecked TODOs only when they are
blocked, require user input, or are explicitly non-actionable context, and state
that reason.
