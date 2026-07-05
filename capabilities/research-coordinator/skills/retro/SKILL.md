---
name: "retro"
description: "Reflect on the current research session and propose instruction improvements."
---

You are reflecting on the current research session to identify improvements for the agent's base instructions. This is a retrospective -- not about what went wrong, but about what can be made better for future research sessions.

Use any extra user text supplied with the skill invocation as feedback to consider.

Set `$PROJECT_DIR` to `/workspace` if that directory exists; otherwise set it to the current working directory.

## Step 1: Gather Context

Detect which instruction file exists in the workspace:
- Check for: `CLAUDE.md`, `GEMINI.md`, `AGENTS.md` (in that order)
- Use the first one found as `$INSTRUCTION_FILE`

Read the following files (skip any that don't exist):

1. `$PROJECT_DIR/REVISION.md` -- previous retrospective entries (if any)
2. The active work branch experiment `SUMMARY.md` if available, plus individual experiment YAML files only when needed
3. The active work branch `report.md` if available -- work-branch-local narrative analysis and report quality
4. The active work branch `TODO.md` if available -- work-branch-local open items and deferred work
5. `$PROJECT_DIR/$INSTRUCTION_FILE` -- the materialized instructions governing this session, including the selected main-agent section
6. The injected Agentic Notes section in `$INSTRUCTION_FILE`, especially project agent-type notes for the active agent type; read on-demand note files only when they are needed to evaluate a concrete note-related issue
7. Run `git log --oneline -30` -- see the commit history (style, frequency, quality)
8. Run `git diff --stat HEAD~5..HEAD 2>/dev/null || true` -- recent change patterns

For work-branch records, use the experiment-log command and direct reads from
the work-state checkout:

```bash
experiment-log summary --project-dir "$PROJECT_DIR" --work-branch "$AR_WORK_BRANCH" 2>/dev/null || true
WORK_STATE_DIR="${AR_STATE_ROOT:-$HOME/.cache/agentic-team}/projects/${AR_PROJECT_ID:?}/work-state/${AR_WORK_BRANCH:?}"
test -f "$WORK_STATE_DIR/report.md" && sed -n '1,220p' "$WORK_STATE_DIR/report.md"
test -f "$WORK_STATE_DIR/TODO.md" && sed -n '1,220p' "$WORK_STATE_DIR/TODO.md"
```

## Step 2: Commandment Compliance

Review compliance with each of the 10 Commandments (Section 1 of the instruction file). For each, assess: **followed**, **partially followed**, or **violated**, with evidence.

| # | Commandment | Status | Evidence |
|---|-------------|--------|----------|
| I | Never break a promise | ? | Did the agent follow through on stated intentions? |
| II | Never manipulate evaluation | ? | Were metrics/test sets/constraints kept unchanged? |
| III | Never fabricate citations | ? | Were bibliography entries verified? |
| IV | Complete all autonomous work | ? | Were tasks left incomplete? Did the agent wait unnecessarily? |
| V | Make it work before moving on | ? | Were methods discarded due to implementation bugs? |
| VI | One variable per experiment | ? | Were experiments properly isolated? |
| VII | Evaluate in tiers | ? | Was the three-tier strategy followed? |
| VIII | Bound your expectations | ? | Were theoretical bounds established before heuristics? |
| IX | Record everything | ? | Are completed experiments logged? Are report details and failures documented? |
| X | Verify before claiming | ? | Were verification scripts created for non-trivial math? |

Also check module compliance if applicable: M1-M2 for math, C1-C4 for compute-intensive research, and N1-N4 for External GPU Job Backend use.

This table goes into the REVISION.md entry.

## Step 3: Analyze the Session

Reflect on these additional dimensions:

### A. Workflow & Process
- Did the experiment loop work well? Were there unnecessary steps or missing steps?
- Was iteration speed good, or did the agent waste time on unproductive paths?

### B. Experiment Log and Report Quality
- Is the shared experiment log complete enough to reconstruct what was run?
- Were completed meaningful experiments routed through the `experiment-logger` subagent when available?
- Were corrections routed through the `experiment-logger` subagent instead of manually altering old experiment fields?
- Was `SUMMARY.md` append-maintained rather than regenerated or hand-edited?
- Is the report clear, well-structured, and useful as a work-branch-local narrative record?
- Are report entries detailed enough to understand methods, analysis, and verification?
- Are analyses insightful or superficial?
- Are results tables properly formatted with clear columns?

### C. Git Discipline
- Are commit messages descriptive and following the prescribed format?
- Is branching used effectively?
- Are commits atomic (one idea per commit)?

### D. Error Handling & Recovery
- Did the agent handle failures well (OOM, NaN, divergence)?
- Were failed experiments documented properly?
- Did the agent recover autonomously or get stuck?

### E. Communication & Autonomy
- Did the agent ask for help at the right times (not too often, not too rarely)?
- Were results reported honestly, including negative results?

### F. Resource Management
- Was local GPU capacity discovered correctly with `nvidia-smi` or `rocm-smi`? (C1-C3)
- If an External GPU Job Backend was active, was backend capacity discovered and used according to N1-N4?
- Were long runs estimated and confirmed before starting?

### G. Agentic Notes Hygiene
- Were injected `always-injected.md` notes treated as active guidance without opening source `always-injected.md` note files?
- Were relevant on-demand notes read before work that depended on those packages, libraries, architectures, benchmarks, or conventions?
- Were reusable lessons routed through the `note-updater` subagent instead of direct note edits by the main agent?
- Were notes kept distinct from work-branch `TODO.md` items and experiment history?

### H. User-Specific Feedback
- Address the user's $ARGUMENTS feedback directly. This is the most important input.
- If the user pointed out something specific, propose a concrete instruction file change for it.

## Step 4: Write to REVISION.md

Update `$PROJECT_DIR/REVISION.md` following these rules. `REVISION.md` is a normal branch-local project file unless the user merges it through ordinary Git workflow.

### If REVISION.md does NOT exist:
Create it with this structure:

```markdown
# Instruction File Revision Notes

Collected observations and improvement suggestions from research sessions.
Each retrospective adds entries; later entries may refine or supersede earlier ones.

---

## Revision 1 -- [DATE]

**Session context:** [Brief description of the research task and current state]

**User feedback:** [What the user said, or "None provided"]

### Commandment Compliance

| # | Commandment | Status | Evidence |
|---|-------------|--------|----------|
| I | Never break a promise | followed/partial/violated | [evidence] |
| ... | ... | ... | ... |

### Proposed Changes

#### [Section of instruction file, e.g. "Section 3: Experiment Logging and Research Record"]
- **Issue:** [What was suboptimal]
- **Suggestion:** [Concrete change to instruction file wording/rules]
- **Rationale:** [Why this would help]

### Things That Worked Well
- [Keep these -- don't fix what isn't broken]

### Open Questions
- [Things that need more sessions to evaluate]
```

### If REVISION.md ALREADY exists:
1. Read the existing content carefully
2. Add a new `## Revision N` section (increment the number) at the END of the file
3. Reference previous revisions where relevant ("Revision 1 suggested X; after further experience, Y is better")
4. If a previous suggestion turned out to be wrong or insufficient, note that explicitly
5. Do NOT delete or modify previous revision entries -- they form a history
6. If the same issue appears again, escalate its priority and refine the suggestion

## Step 5: Summarize to the User

After writing REVISION.md, give the user a concise summary:
1. Commandment compliance overview (how many followed/partial/violated)
2. The top 3 most impactful proposed changes
3. Any patterns across multiple retrospectives (if applicable)
4. Ask if they want to elaborate on any point or add more feedback

## Guidelines

- Be **specific and actionable**. Don't say "improve error handling docs". Say "Add an example to Troubleshooting for 'CUDA version mismatch' with fix 'check `nvidia-smi` vs `torch.cuda.get_device_capability()`'".
- Propose **exact wording** for instruction file changes when possible. Quote the current text and show the proposed replacement.
- Be **honest**. If the agent followed instructions perfectly and things still went wrong, the instructions need changing, not the agent.
- Be **conservative**. Don't propose removing rules that exist for good reason (Commandments, verification). Instead, propose clarifications or additions.
- Focus on **high-leverage changes** -- small wording tweaks that would have prevented significant issues or substantially improved output quality.
- Note when something is a **one-off** vs a **pattern**. One-off issues might not warrant an instruction change; recurring patterns definitely do.
