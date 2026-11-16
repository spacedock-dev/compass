# Launcher declarations and local groups

The [runtime architecture](design-runtime-architecture.md) owns the module map.
[Security](../SECURITY.md#launcher-parent-declarations-and-group-labels) owns the trust boundary.

## Declaration ingress and lifetime

Use an environment variable on the child, copied only by its SessionStart hook, rather than a
new route. The existing per-harness event capability admits the envelope; its session ID selects the
claim owner without independently authenticating that session. No inference from cwd, process
trees, titles or timing is permitted. Gemini and
Droid share the standalone forwarder; Antigravity has a different event path and does not read
this variable. The hook accepts its own four harness tokens. The server can retain an unknown
syntactically valid token as an explicit unmatched declaration, without discovering any row.

Claims are bounded by the existing event session cap, with new identities refused at capacity.
They survive later events and resumes that omit or malform the variable, and are replaced only
by another valid SessionStart claim. Later events can refresh retention but cannot introduce a
claim. This avoids a resume silently detaching a worker.

The original memory-only choice lost long-running coordinators on dashboard restart, so claims
now use a small private store with the I/O primitives' owner-only directory, regular-file read,
atomic write and stable lock. Read-modify-write preserves concurrent writers, at most 512 claims
and 256 KiB. Reload validates schema, identities and finite positive timestamps without renewing
them. Expiry waits until row visibility is known: an old visible coordinator survives, while an
absent claim expires after the focus-target inactivity TTL. A malformed or unreadable store is
refused rather than replaced. Failed writes are diagnosed and leave bounded claims in memory;
collection must not erase that fallback. `--forget` removes the claims, leaving the stable lock
file. `--no-events` constructs no coordinator and restores nothing. Persistence cannot recover
SessionStart events never received, including claims lost before upgrading from memory-only
storage. Ended rows can still describe their declared parent while they remain on the board.

## Resolution and cycles

Resolve after lifecycle overlays and annotation attachment, against the final rows remaining
after dismissal subtraction. Reuse event identity normalizers, including Claude full UUID to
eight-character published key. Canonical UUID hex matching ignores case but returns the original
published identity. Both parent and child matches must be unique; full Claude identities also
check the row's resume identity when present. Codex never prefix-matches. Only a matched row
produces a non-null parent. Unknown rows,
self-links and every edge belonging to a cycle are unlinked. An acyclic descendant of a cycle
member may still link to that visible row. Iterative graph walks avoid recursion on a hostile
chain up to the event cap. Raw claims never enter the patchable display-field set or history:
only the collection publishes resolved identities, not the envelope.

## Working holds

Resolve from leaves to ancestors after native and event state settles. A Working child without a
finished or ended mark can hold an otherwise Idle, non-ended parent Working. A parent's input
wait always wins. The deadline uses child activity plus the existing Claude or Codex
tool-in-flight ceiling; Gemini and Droid use the smaller of those two ceilings. No collection
clock renews a hold. A chained hold carries its underlying deadline, so adding ancestors buys no
more time. A stopped parent may still wait on a working child, but an ended parent cannot.
A finished intermediate row cannot pass that hold up to its own parent.

When several eligible children work, name the most recently active; equal activity sorts by
ascending harness and published sid. Native Working parents keep their native detail and have
no `waiting_on_child`, since the declaration is not holding them Working. No goal is inherited.
A held row carries `declared_native_state` with its actual pre-hold `state`, `active` and
`state_detail`, preserving those values through serialization. The shared `model_row` boundary
restores it and removes display metadata. Automatic scheduling, project context, reading
production, Live estimates and drift derivation use that boundary. Drift and footer cache inputs
normalize before their field projections discard the snapshot. Native active idle scan rows must
remain active: inventing `active=False` changed observer membership. A declaration cannot change
reading scope or facts, footer inputs, or buy an automatic model call.

## Group storage and model isolation

Keep group on the annotation entry, outside intent revisions. A group-only record has no
revision; adding intent later mints its first revision normally. Atomic annotation locks, masking,
byte caps and eviction remain the store's responsibility. Intent entries outrank group-only entries;
a group-only write refuses rather than evicting another session's goal or reading at either cap.
A group update does not revise intent,
move its reading window, retract an assessment or start a model call. Clearing the own label
restores inheritance. Discarding an annotation also removes its own label. A later label save on a discarded
session preserves the discard marker and its revision guard, and admits no reading or other
intent metadata. Forget sweeps that marker and preserves the label.

Inherit through linked ancestors, stopping at the nearest own label. Disabled annotations mean
no stored labels are read, including parents, so inheritance is empty too. None of these fields
enters history. Source inventories read transcripts by the existing selected session identity;
prompt builders still select only intent words and admitted source facts. The terminal write
reuses goal-save transport and admission guards, but allows piped stdout because launchers are shell scripts.
It requires an explicit selector to avoid writing against an inherited outer-session marker.
