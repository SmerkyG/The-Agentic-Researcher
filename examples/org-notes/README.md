# Example Org Notes Repo

This directory is a starter layout for an optional Agentic Researcher org notes
repo. Copy these files into a separate Git repo when you want organization-wide
or role-specific guidance shared across AR projects.

An empty org notes repo is a valid blank shared memory: AR can create org and
role notes there over time via the note-updater flow. These starter files are
useful when you want initial guidance to be injected or listed immediately.

Recommended starter files:

- `agents/<agent_name>.md`: optional org-provided subagents shared by every AR
  installation configured with this org repo.
- `notes/always-injected.md`: short guidance every agent in the org should see.
- `notes/<topic>.md`: on-demand notes for packages, libraries, infrastructure,
  datasets, benchmarks, or conventions.
- `roles/<role_id>/notes/always-injected.md`: short guidance for agents launched
  with that `AR_ROLE_ID`.
- `roles/<role_id>/notes/<topic>.md`: on-demand notes for that role.

Keep `always-injected.md` concise. Put detailed or rarely needed information in
topic notes so agents can read it only when relevant.

Org-provided agents render after AR's built-in agents. If an org agent has the
same `name` as a built-in agent, the org agent wins.
