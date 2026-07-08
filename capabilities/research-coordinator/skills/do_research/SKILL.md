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
- `condensed_report.md` is the short rolling condensed report of current
  findings when this research workflow creates it. Keep it to about one page by
  rewriting it instead of appending chronology.
- `report.md` is the newest/current mutable work-branch-local narrative page
  when this research workflow creates it. Older pages are named
  `report_pageN.md`, where `report_page1.md` is the first/oldest archived page
  and higher numbers are newer. Before adding new narrative report content,
  run `research-coordinator-report-rollover --work-state-dir "$WORK_STATE_DIR"`;
  when the current `report.md` already exceeds 300 lines, it archives that page
  whole to the next `report_pageN.md` and starts a fresh `report.md`.
- `TODO.md` is the mutable work-branch-local checklist when this research workflow
  creates it.
- `images/` stores report-ready figures referenced by report pages.

Code branches and experiment subbranches hold code. Do not treat worktree
`condensed_report.md`, worktree `report.md`, worktree `report_pageN.md`, worktree
`TODO.md`, or worktree report `images/` as canonical work-branch records.

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

3. Read work-branch `condensed_report.md`, current `report.md`, and `TODO.md` only when
   needed. Read older `report_pageN.md` files only when their archived context
   is relevant:

   ```bash
   test -f "$WORK_STATE_DIR/condensed_report.md" && sed -n '1,180p' "$WORK_STATE_DIR/condensed_report.md"
   test -f "$WORK_STATE_DIR/report.md" && sed -n '1,220p' "$WORK_STATE_DIR/report.md"
   test -f "$WORK_STATE_DIR/TODO.md" && sed -n '1,220p' "$WORK_STATE_DIR/TODO.md"
   ```

4. Run `git log --oneline -20` and `git status`.
5. Summarize the current state to the user:
   - Best result so far and which experiment achieved it
   - What was tried last and whether it worked
   - What's next from the active work-branch plan, work-branch TODO, current
     report page, or last logged experiment's next steps
6. Ask the user if they want to continue the planned direction or pivot.
7. Continue the autonomous experiment loop. Completing one `TODO.md` item is
   not a stopping condition; after checking off finished items, pick the next
   unchecked item, experiment, or analysis step and keep going unless user input
   is required.
   If you add a next TODO item, begin it immediately unless it is blocked or
   requires user input. Do not avoid this by leaving a concrete autonomous next
   step only in report prose, `condensed_report.md`, or the final response; if
   it is specific enough to call the next experiment, metric, verification, or
   implementation step, it belongs in `TODO.md` and the loop continues.

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
   work-branch plan directly; normal learned note updates go through
   `research-finalizer` after completed research results or through
   `note-updater` for standalone lessons. Retry the relevant subagent once if
   spawning fails, and alert the user if it still cannot be spawned instead of
   silently calling `agentic-notes` directly.

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

5. Initialize work-branch `condensed_report.md`, `report.md`, and `TODO.md` in the
   work-state worktree. These are normal files in that worktree, not Agentic
   Notes commands:

```bash
cat > "$WORK_STATE_DIR/condensed_report.md" <<'MARKDOWN'
# Condensed Report

Rewrite this file as the branch evolves. Keep it to about one page with the
current best findings, important negative results, open risks, and next
direction.
MARKDOWN

cat > "$WORK_STATE_DIR/report.md" <<'MARKDOWN'
# Research Log

Use this newest/current report page for branch-local narrative analysis,
derivations, figures, verification notes, and selected result tables. Embed
LaTeX math when needed, for example `$O(n \log n)$` or display equations.

Before adding new narrative content in later sessions, run
`research-coordinator-report-rollover --work-state-dir "$WORK_STATE_DIR"`.
If this current page already exceeds 300 lines, the helper archives it whole to
the next `report_pageN.md` file and starts a fresh `report.md`; do not split old
report pages by heading or section count.
MARKDOWN

cat > "$WORK_STATE_DIR/TODO.md" <<'MARKDOWN'
# TODO

- [ ] Run baseline evaluation
MARKDOWN

mkdir -p "$WORK_STATE_DIR/images"
git -C "$WORK_STATE_DIR" add condensed_report.md report.md TODO.md images/
for page in "$WORK_STATE_DIR"/report_page*.md; do
  [[ -e "$page" ]] && git -C "$WORK_STATE_DIR" add "$(basename "$page")"
done
git -C "$WORK_STATE_DIR" commit -m "work-state: initialize $WORK_BRANCH research records"
git -C "$WORK_STATE_DIR" push
```

Use Markdown headings and tables in report pages; embed LaTeX math only when it
helps the derivation. Before each work-state commit, update `condensed_report.md` and
enforce report pagination: `report_page1.md` is oldest, higher page numbers are
newer, and `report.md` is newest/current. Before adding new narrative report
content, run `research-coordinator-report-rollover --work-state-dir "$WORK_STATE_DIR"`;
it rolls over only when the current `report.md` already exceeds 300 lines, and
it archives that page whole instead of splitting sections. Use Markdown image
links for figures, embedding PNGs such as `![caption](images/name.png)` rather
than PDF-only links. Save report-ready PNG/PDF figures under `$WORK_STATE_DIR/images/`
and commit `images/` with the report pages even though those files are binary.
Keep raw arrays, checkpoints, full logs, datasets, and other bulky generated
artifacts under `$AR_ARTIFACTS_DIR` instead. Use a unique run or experiment
subdirectory for new writes so parallel AT work does not overwrite shared
project artifacts. Use `TODO.md` checklist items in `- [ ] item` format.

6. Proceed with initial setup:
   - Explore the codebase structure and understand the architecture
   - Check local GPU availability with `nvidia-smi`; if unavailable, try
     `rocm-smi`
   - Install dependencies with `uv sync`
   - Run the baseline evaluation command from the research plan
   - Update work-branch `condensed_report.md`, report pages, `TODO.md`, and report
     figures synchronously in the work-state worktree before any slower
     bookkeeping delegation
   - If the baseline is a meaningful completed experiment, read the
     `research-finalizer` `Contract:` path from the generated Available
     Subagents catalog and launch `research-finalizer` with
     `finalize_current_research_context: true` so experiment logging, note
     triage/update, work-state commit/push, and code commit handoff for an
     already-captured snapshot can proceed without blocking the next research
     decision. On Codex,
     subagent contracts live under `.codex/agents/`; do not search `.agents`.
     For Codex typed subagents, include the contract's compact
     `context_packet` in the first spawn request and do not request a
     full-history fork with `agent_type`; set the non-fork option explicitly
     when the tool exposes one (`fork_context: false` or `fork_turns: "none"`).
     If the baseline produced code changes to commit, create and inspect the
     explicit-path `branch-snapshot` synchronously before launching the
     finalizer and pass the snapshot path in the request.
     Once the handoff is accepted, treat it as fire-and-forget background work:
     keep the subagent id/status path if one is available, but do not poll or
     wait merely to report finalizer status.
   - Commit only code/config/script changes that belong in the code branch; do
     not commit work-branch Agentic Notes, `condensed_report.md`, report pages,
     `TODO.md`, or report `images/` to the code branch
   - Begin the autonomous experiment loop and keep repeating it until no useful
     autonomous work remains

Before any final response after using this skill, inspect the active work-branch
`TODO.md`. If unchecked actionable items remain, continue the experiment loop
instead of reporting completion. Return with unchecked TODOs only when they are
blocked, require user input, or are explicitly non-actionable context, and state
that reason. Also check any next direction you intend to mention: a concrete
autonomous next action must be represented in `TODO.md` and started, or clearly
labeled as blocked / requiring user choice.
