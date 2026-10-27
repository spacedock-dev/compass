# Plan: native Linux/Windows/WSL notifications, and other open items

Status: unshipped. This is the only remaining work from the cross-platform effort, plus the items
that were deliberately deferred with a named condition for revisiting them.

Everything that shipped is documented in [`COMPATIBILITY.md`](../../COMPATIBILITY.md) (behavior) and
[`design-cross-platform.md`](../design-cross-platform.md) (rationale). Delete this file once its
contents ship or are dropped.

---

## 1. Native notification backends behind `--notify`

Today the server has one native backend, `osascript` on macOS. Linux and Windows fall back to the
browser Notification API, which only fires while a dashboard tab is open. The hook path
(`POST /api/notify`, which exists precisely to work with no tab) therefore delivers nothing on those
platforms.

Deliver `notify-send` on Linux, `wsl-notify-send.exe` (falling back to `powershell.exe`) on WSL, and
a PowerShell toast on Windows. Each sits behind `--notify` and is written as a pure selector
function per design decision D-4, so the Ubuntu runner can exercise it.

Four constraints on code that does not exist yet:

- Toast XML is an injection surface. `notification_text` strips control characters but not `<`, `>`
  or `&`. Any XML-shaped backend must XML-escape the message and pass arguments via argv, never
  through a shell. Ruff's `select = ALL` will also demand a justified `S603`/`S607` suppression.
- Delivery can never be guaranteed. Windows toasts want a registered AppUserModelID and an
  interactive session, `notify-send` wants a graphical user D-Bus session, and WSL interop can be
  disabled by policy. The honest exit criterion is graceful degradation plus a *reported* delivery
  status, so every backend must no-op with a log rather than raise. Ship it labeled experimental.
  That reported status now exists and has a shape: `deliveries.py` holds five outcome tokens, a
  notifier returns one of them, and a new backend adds a value rather than changing the record. A
  backend that cannot deliver returns the refused or the did-not-return token, and the lane token is
  reserved for a platform this build has no backend for at all. The cooldown floors are spent before
  the call and refunded when the outcome says there was no lane, so a platform gap does not silence
  the next real transition.
- Latency is fine, but holding the lock is not. A backend that spawns a subprocess can block for
  hundreds of milliseconds, and all three of these are slower to start than `osascript`. That is
  safe only because the server is threaded and both dispatch sites invoke the notifier *after*
  releasing `_lock`. Never call a backend while holding it. Probing for an available backend at
  startup is therefore an optimization rather than a correctness requirement. An earlier revision of
  this plan had that backwards.
- The test suite already refuses it. `support.forbid_native_notifications` reads the refused set off
  `native_notifier`, so a new backend is covered the moment the selector names it, and a test that
  spawns it for real fails with an `AssertionError` instead of notifying whoever ran the suite. A
  test that needs the composition to run has to suppress only the process, through
  `support.short_circuit_native_notifications`. Four tests sent real macOS banners before that
  refusal existed, which is why it is not keyed to `osascript`.

Per D-3, `--notify` must state which owner it disables.

Related gap: idle nudges (`idle_prompt`) pop without marking the session blocked. macOS delivers
them, and the page now raises a one-shot notification of its own for an arriving `ask_operator`
question, so "the page only notifies on transitions" has stopped being the reason. A one-shot alert
is deliverable there whenever the payload carries a natural unique key, which the ask lane has and an
idle nudge does not: what is missing is a per-nudge identity in `/api/data`, not a channel the page
cannot use. Still worth doing alongside the native backends rather than bolting onto the page, and the
Linux and Windows halves of this section are unchanged: an ask there still needs a tab open.

## 2. Deferred, with the trigger that should revive them

- NTFS last-write lag. Windows does not fully update a file's last-write time while a writer holds
  the handle open. Working/Idle is largely mtime-based, so an actively generating Windows session
  could read Idle. The premise is documented by Microsoft but unverified here, and whether it bites
  depends on how often each harness flushes and closes. Reshaping state detection across ten
  collectors on an unverified premise is exactly what D-6 forbids.
  Revisit when a Windows user reports a session stuck on Idle while visibly generating, or when
  `--diagnose` shows a growing store with a stale mtime. The fix is a size/WAL-size delta between
  polls, preferring parsed event timestamps with mtime as fallback.
- WAL across a network or synced home. SQLite's write-ahead log needs shared-memory coordination on
  a single host. Roaming profiles, UNC/SMB homes and cloud-synced directories can present
  inconsistent `db` / `-wal` / `-shm` triples, and the symptom is an empty harness. No detection
  exists; it should warn rather than report nothing.
- Coarse filesystem timestamps. FAT/exFAT write time has two-second resolution, and network or
  translated filesystems can coarsen it further. The title caches keyed on `(st_mtime_ns, st_size)`
  can therefore serve a stale title after a same-size rewrite. Unmitigated, low impact.

## 3. Questions only a real machine can answer

`--diagnose` output from any Windows user substitutes for all four.

1. One Claude `~/.claude/projects/` directory name on native Windows, plus the working directory it
   came from. That is the only way to settle how a drive letter and backslashes are encoded.
2. Whether Codex writes `\` in `cwd` / `agent_path` on Windows.
3. Goose and OpenCode Windows store paths, confirmed against upstream source rather than blog posts.
4. Whether `cursor-agent` and Antigravity CLI ship native Windows builds at all. If they do not, the
   matrix says eight harnesses on Windows rather than ten, which is a documentation outcome and not
   a failure.

## 4. Open maintainer decisions

- The `platform = "darwin"` mypy pin. Its stated justification is no longer true, because
  `mypy --platform linux` passes clean on the current tree: the remaining platform branch goes
  through `native_notifier(sys.platform)`, which mypy does not narrow. Delete the pin or write a
  true justification. Leaving a false one invites a wrong conclusion.
- The coverage ratchet. The figures recorded in `pyproject.toml` predate the cross-platform test
  suite and understate real coverage substantially. Read the current number off an Ubuntu gate run
  and ratchet `fail_under` in a dedicated PR, so the move is visible on its own.
- Undocumented store environment variables. `XDG_DATA_HOME`, `LOCALAPPDATA` and `APPDATA` move real
  stores but are absent from `STORE_ENV_VARS`, so `--diagnose` reports "overrides: none" while they
  are in effect. Adding them makes the diagnostic honest, but the documentation-matches-code test
  then requires the skill body to mirror them, and D-6 argues against advertising an override whose
  upstream semantics are not documented. Decide before documenting them either way.
