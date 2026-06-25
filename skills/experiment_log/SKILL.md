---
name: "experiment_log"
description: "Record project experiments in the Git-backed Agentic Researcher experiment log."
---

Meaningful experiments are recorded in the project `agentic/state` checkout, not only in chat or local scratch files. This log is the shared cross-agent experiment ledger. Read `.agentic/experiment-log/SUMMARY.md` first and open individual YAML files from `.agentic/experiment-log/experiments/` only when needed.

Use `${AR_NOTES_CLI:-scripts/ar-notes} log-experiment --request REQUEST.yaml --project-dir PATH` to record a completed experiment. The helper assigns project-local counter IDs such as `E0001_alice_triton-power2-shape-test`, writes one YAML file, increments `COUNTER.yaml`, appends exactly one row to `SUMMARY.md`, commits, and pushes. Agent metadata such as `source.actor_id` and invocation IDs belongs inside YAML metadata, not in the experiment ID.

Use `report.tex` for branch-local narrative analysis and `TODO.md` for branch-local checklists. They are normal project files, not the shared experiment index or multi-agent queue.

Do not regenerate `SUMMARY.md` during normal logging. If a result needs correction, use `${AR_NOTES_CLI:-scripts/ar-notes} log-correction --request REQUEST.yaml --project-dir PATH`; it appends a correction entry to the original experiment YAML file and appends a correction row to `SUMMARY.md`. Do not manually alter existing experiment fields.

If a push conflict occurs, let the helper pull latest, discard the failed generated ID if needed, recompute the next experiment or correction ID from the refreshed state, and retry. Never force-push.
