# Intent and drift teammate evidence

The owner retired the Intent and drift study on 2026-11-01, and the tooling that produced the records it describes was removed; the records are kept as written.

[Share the sidecar prompt](PROMPT.md) with a developer who wants to offer feedback from real Claude Code work. Their agent can run current `main` against a recent session and record what the drift panel says. This is optional exploratory evidence, with agent-operated and human-operated steps identified separately.

The owner removed the cold-study requirement on 2026-10-06. No cold participants need to be recruited, and no cold-study pass is claimed. The [archived protocol](COLD_STUDY_PROTOCOL.md) records the former procedure. For optional feedback, use the [kickoff and consent note](PARTICIPANT_KICKOFF.md) and [run template](RUN_TEMPLATE.md). Application verification and producer accuracy qualification remain separate requirements.

Starting Compass scans available local session stores across its supported harnesses, not just the three Claude Code sessions an agent shortlists. Its loopback board can display session titles and prompts. Each participant must know that before the sidecar starts. The agent should inspect and report only the selected sessions, and the participant decides separately whether to allow a model reading in the browser.

This repository is public. Commit only a participant-approved, redacted copy of the run template under this directory. Keep raw transcripts, saved goals, checklist text, clipboard contents, local paths, session IDs, and unredacted screenshots out of Git. Save original captures under the gitignored `docs/screenshots/intent-and-drift-sidecar/` tree. Keep that checkout available until a person reviews the captures and any approved evidence reaches the development record. A public report can link to a public verdict without repeating private material. Use a branch and a PR into `main` for the public report; the [PR workflow](../../../AGENTS.md#pr-workflow) applies.
