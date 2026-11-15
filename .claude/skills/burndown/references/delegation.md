# Delegation mode

Read this when the caller passes `--delegate`, or asks in their own words for the session to
coordinate and hand the work to Codex and Antigravity (AGY). The shared stages stay in force:
delegation changes **who** runs the plan, build and review stages, not what those stages require.

The point is cost. Measured 2026-11-14: one milestone run with Claude subagents at every stage
spent about 1.5M Claude tokens; the next, delegated, kept the orchestrating session's own spend to
coordination while Codex and AGY carried the deep dives, builds, lenses and arbiter.

## Who does what

| Work | Delegated mode | Why |
|---|---|---|
| Steps 1, 2, 5, 6, 7: load, plan, stack and land, reconcile, close | Orchestrator | Tracker writes, `gh stack` and merges need the session's tools and the owner's approvals. |
| Mode 1 and Mode 2 walks, the real-session check | Orchestrator | Only the orchestrator has the browser and a logged-in `claude`. |
| Step 3 deep dive | Codex, at the plan stage's setting, inside the build run | Neither CLI can run `linear-deep-dive`; the builder writes the analysis file first (below). |
| Step 4.1, 4.2, 4.5, 4.6: tests, code, `sync-docs`, fix rounds, bundle | Codex | Long agentic edits with a test loop. |
| Step 4.4 lenses | Mixed: Codex and AGY | Two model families find different defects; a lens never shares a family with every other lens. |
| Step 4.4 arbiter | Codex | It reproduces findings, so it needs a working shell and test runner. |
| Small inline fixes (a few lines and a test) | Orchestrator | Five minutes inline against twenty or more for a fresh run. |

The orchestrator still reads every hand-back, every lens report and the arbiter's verdict before
acting on any of them, and it still owns every decision a stage surfaces. A delegate's "done" is
a claim to check, not a fact.

## Choose the models at run time

Model names change between runs, and a name the caller remembers may not exist. Before
recommending anything, read the live catalogs:

```bash
# Codex: slug, supported efforts and visibility; recommend only visibility "list"
codex debug models | python3 -c 'import json,sys
for m in json.load(sys.stdin)["models"]:
    print(m["slug"], [l["effort"] for l in m["supported_reasoning_levels"]], m.get("visibility"))'
grep -E '^model' ~/.codex/config.toml   # the owner's configured default and effort
# AGY: Gemini models, one row per model-effort variant
perl -e 'alarm shift; exec @ARGV' 20 agy models
```

Measured 2026-11-15: an owner named `gpt-6.1-astra` and `gpt-6.1-luna`, and the catalog held
`gpt-6-astra` and `gpt-6-luna`; a run launched with the remembered name sat idle for twenty minutes
before anyone noticed. If a requested name is missing, say so and offer the closest listed slug.

Codex takes effort separately (`-c model_reasoning_effort=<level>`); AGY encodes it in the model
name (`gemini-4-argon-high`). Recommend from the newest listed generation, and map the planning
reference's stage table onto it:

| Stage | Default | Full-adversarial group |
|---|---|---|
| Plan (inside the build run) | Codex newest general model · medium | Codex · high |
| Build and fix rounds | Codex · medium; high for a web-surface group of L or more, `config.py` or the shipped `SKILL.md` | Codex · high |
| Review lenses | one Codex · high and one AGY · high | add a second AGY lens of a different model, all at high |
| Arbiter | Codex · high, a different model from the builder when one is listed | Codex · high |

Never recommend `xhigh`, `max` or `ultra` unless the caller asks. Ask the stage questions as the
planning reference says, naming the exact slugs and efforts, with the recommendation first. When
the owner has a configured Codex default that a run measured as reliable, prefer it for building.

## Dispatch mechanics

Each item was measured; each cost a stalled or wasted run when missed.

- **Close stdin.** `codex exec` prints `Reading additional input from stdin...` and waits for EOF
  when stdin is an open pipe. Always end the command with `< /dev/null`.
- **Bound every run.** macOS has no `timeout`: wrap each call in
  `perl -e 'alarm shift; exec @ARGV' <seconds> ...`, about twice the stage's usual time, and run it
  in the background so its exit wakes the orchestrator. A builder for an M issue took 25 to 50
  minutes; a lens 15 to 40; an arbiter 20 to 40.
- **Codex needs loopback.** The `workspace-write` sandbox cannot bind `127.0.0.1` (`EPERM`), and
  many suites here need it (`test_http_api`, MCP and hook transports, `pnpm test:stories`). Give
  builders and reviewers `--sandbox danger-full-access`, and confine them by giving each its own
  worktree, never the main checkout.
- **Codex command shape.**
  `codex exec -m <slug> -c model_reasoning_effort=<level> --sandbox danger-full-access -C <worktree> -o <handback.md> "$(cat <prompt.md>)" < /dev/null > <log> 2>&1`.
  `-o` writes the final message, which is the hand-back the orchestrator reads.
- **AGY command shape.** Put `-p` last: `agy -p --model X ...` takes `--model` as the prompt.
  `cd <worktree> && agy --model <variant> --dangerously-skip-permissions --add-dir <probe-dir> -p "$(cat <prompt.md>)" > <report.md>`.
  `--mode auto` is not available on every account; AGY then warns and runs its default mode,
  which worked for read-and-probe lenses.
- **No tracker, no Claude skills.** Neither CLI has the Linear connector or this session's skills.
  Paste the issue's user value, evidence, scope and acceptance criteria into the prompt, plus the
  container's `Read before building` notes for that issue. Codex discovers the repository skills
  through `.agents/skills/`, so name `sync-docs` by that path; TDD and the deep dive are written
  out as steps.
- **One prompt preamble, one task file per layer.** The preamble carries the repository rules a
  builder needs: read `AGENTS.md`; deep dive into a named analysis file first; failing test first;
  run only the touched modules with a `-j` share; ruff, format, mypy, `validate_plugins.py`; DCO
  commits through `/usr/bin/git` with `SKIP_CLAUDE_PRECOMMIT=1` when no frontend changed; no push,
  no PR, no rebase; never a version field or the `docs-synced-through` marker; the contention list
  from **AGENTS.md, "Parallel Work"**; hooks abstain rather than fail. The task file carries the
  issue text and the layer's contract notes. Namespace every scratch file per layer.
- **Reviewers get detached checkouts.** Create one detached worktree per lens at the reviewed head,
  forbid tracked edits, and give each a probe directory outside the repository for its scripts.
  A lens must reproduce before it reports and mutation-test the new guards. The arbiter gets every
  lens report and probe directory and returns confirmed, refuted and pre-existing verdicts, a fix
  list in build order with the test that must fail first, and a file list.
- **Fix rounds go back to Codex.** Resume nothing: start a fresh Codex run in the layer's worktree
  with the arbiter's fix list, the original task file and the analysis file. A builder that edits
  a lower layer's file is a restack the orchestrator does, never the builder.

## When the stages disagree

Two lenses can pull in opposite directions (one wants fewer symlinks followed, one found a real
layout the change breaks). The orchestrator writes one rule that satisfies both, hands that rule to
the arbiter to test, and records it in the pull request as the orchestrator's call. Writing it to
the tracker as the owner's decision needs the owner's words.

## Reporting

Name, for every delegated run, the CLI, the model slug and the effort it actually ran with, and
the wall clock it took. Delegated token spend is not on the session's meter; say so rather than
reporting it as zero.
