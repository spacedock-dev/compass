"""Session identity, shape, and deterministic aggregation."""

from __future__ import annotations

import hashlib
import ntpath
import os
import posixpath
import re
from datetime import UTC, datetime
from functools import lru_cache
from typing import TYPE_CHECKING, Any, Final, TypeAlias

if TYPE_CHECKING:
    from collections.abc import Iterable

    from .config import RuntimeConfig

Session: TypeAlias = dict[str, Any]


def encoded_home_prefix(home: str) -> str:
    """Reproduce how Claude encodes ``home`` into a ``projects/`` directory name.

    Claude turns a working directory into a directory name by replacing path
    separators with ``-``; stripping that prefix is what leaves a readable
    project label. Replacing only ``/`` worked on POSIX and did nothing on a
    Windows home, so every Claude row there showed the whole encoded path
    instead of the project.

    Backslash and the drive colon are folded too. The exact Windows encoding is
    not documented, so this is deliberately non-destructive: if it turns out to
    differ, the prefix simply does not match and project_label() shows the full
    name — exactly what it does today.
    """
    return re.sub(r"[/\\:]", "-", home)


def project_label(config: RuntimeConfig, dirname: str) -> str:
    """Shorten an encoded project directory name to just the project part."""
    dirname = dirname.removeprefix(encoded_home_prefix(config.home))
    return dirname.lstrip("-") or "(home)"


# How many segments a label built by joining path segments may keep. The same
# figure `history.PROJECT_SEGMENT_CAP` applies to the `/` form, written twice
# rather than shared because `history` is a leaf over `config` alone and may not
# import this module. Both implement the
# [history contract](SECURITY.md#local-history-the-session-history-store),
# which authorizes a derived two-segment label and nothing wider.
PROJECT_SEGMENT_CAP: Final = 2


def bounded_project_label(config: RuntimeConfig, dirname: str) -> str:
    """``project_label`` capped to the last two segments of the encoded path.

    The fallback three collectors reach when a transcript carries no ``cwd``:
    measured, 29 of 3,888 real transcripts on one machine. ``project_label``
    strips the encoded home prefix and returns *every* remaining segment joined
    by ``-``, which is a whole home-relative path. One real store held
    ``repos-recce-recce-cloud-infra--claude-worktrees-drc-3976-finish``.

    The cap is here rather than downstream because this is the only place the
    difference is known. A consumer sees one string, and ``my-cool-project`` and
    ``alpha-beta-gamma`` are the same shape to it: the history store bounded the
    dash form for a while and truncated correct labels, so a project one
    directory under ``$HOME`` grouped under a different name than the live board
    (DRC-4044).
    decision-history: DR-8 | 4de75d29 | repaired grouping bug; trim at label construction
    Here the label is being built by joining path segments, so
    trimming it is reading the string the way it was written.

    The trade is stated rather than hidden: a directory genuinely named
    ``work-my-repo`` under ``$HOME`` reads as ``my-repo`` on the rows that lack a
    ``cwd``. That is a grouping cost on 0.75% of rows, against a home-relative
    path in a fourteen-day store, which ``SECURITY.md``'s never-list calls a
    security bug.
    """
    label = project_label(config, dirname)
    if label != "(home)":
        walked = _walk_encoded(config.home, label, config.os_name == "nt")
        if walked:
            return "/".join(walked[-PROJECT_SEGMENT_CAP:])
    return "-".join(label.split("-")[-PROJECT_SEGMENT_CAP:])


# A directory name may itself contain the separator the encoding uses, so the
# string cannot say which dashes were `/`. The machine that wrote the store is
# the machine reading it, which `project_from_cwd` already relies on for its
# path rules, so the directory tree settles it: walk the segments and keep the
# longest candidate that is a real directory at each level. `work-my-repo`
# matches whole at the first level; `repos-recce-compass` matches three levels
# down. Measured before this existed: 413 of 831 Claude transcripts for one
# repository carried no `cwd`, and the board drew that repository twice
# (DRC-4629).
#
# It fails closed. An unresolvable name keeps the dash form, because a wrong
# join merges two projects that are genuinely different, which is worse than
# the split it replaces.
_MAX_ENCODED_SEGMENTS: Final = 24


@lru_cache(maxsize=512)
def _walk_encoded(home: str, relative: str, nt: bool) -> tuple[str, ...] | None:
    """The real path segments behind a dash-encoded name, or nothing.

    Cached per encoded directory rather than per session: one label serves
    every transcript under it, and 413 rows resolving to one directory would
    otherwise be 413 stat sweeps.
    """
    path = ntpath if nt else posixpath
    segments = relative.split("-")
    # A bound, so a pathological name cannot turn a quadratic candidate sweep
    # into a visible pause. Ten segments was the longest real one on record.
    if not segments or len(segments) > _MAX_ENCODED_SEGMENTS:
        return None
    found: list[str] = []
    here = home
    index = 0
    while index < len(segments):
        for end in range(len(segments), index, -1):
            candidate = "-".join(segments[index:end])
            nxt = path.join(here, candidate)
            try:
                matched = os.path.isdir(nxt)
            except OSError:
                return None  # an unreadable tree resolves nothing rather than guessing
            if matched:
                found.append(candidate)
                here = nxt
                index = end
                break
        else:
            return None
    return tuple(found)


def project_from_cwd(config: RuntimeConfig, cwd: str) -> str:
    """``<parent>/<basename>`` for a working directory, ``""`` when unusable.

    One directory has to read the same on every harness row, so this is the
    single rule they all share. Bare basename was the old per-collector rule
    and it collapses every checkout named ``subspace`` into one label; two
    segments keep sibling worktrees apart without pasting a whole path into
    the row.

    Separators are the host's, via ``ntpath``/``posixpath``, never a hand-rolled
    split on both. ``docs/design-cross-platform.md`` rejects that helper outright:
    ``\\`` is a legal POSIX filename character, so splitting on it turns one
    directory named ``my\\proj`` into two. Compass only ever reads stores written
    on the machine it runs on, so the host's own rules are the correct ones.

    A path under the configured home is labelled relative to it, because
    ``project_label`` strips the home prefix and the two have to agree: ``~/foo``
    reads ``foo`` from either, never ``<username>/foo``.

    ``config.home`` and ``config.os_name`` carry those two facts, so one runner
    exercises both platforms (design decision
    [D-4](docs/design-cross-platform.md#d-4)).

    Callers apply their own fallback to ``""`` — the harness name, or the
    encoded-directory label for the two collectors that have one.
    """
    path = ntpath if config.os_name == "nt" else posixpath
    if not cwd or not path.isabs(cwd):
        return ""  # a relative cwd names no project; fall through to the caller
    home_dir = config.home

    def trim(value: str) -> str:
        seps = path.sep + (path.altsep or "")
        return value.rstrip(seps) or value

    # normcase folds Windows case *and* separators, and preserves length, so
    # the comparison is spelling-independent and the slice below stays valid.
    cwd_cmp, home_cmp = path.normcase(trim(cwd)), path.normcase(trim(home_dir))
    if cwd_cmp == home_cmp:
        return "(home)"
    rest = trim(cwd)
    if home_cmp and cwd_cmp.startswith(home_cmp + path.sep):
        rest = rest[len(trim(home_dir)) :]
    else:
        rest = path.splitdrive(rest)[1]  # "C:" names no project
    if path.altsep:  # Windows accepts either spelling; POSIX has no altsep
        rest = rest.replace(path.altsep, path.sep)
    parts = [p for p in rest.split(path.sep) if p and p != "."]
    if any(p == ".." for p in parts):
        return ""  # an unresolved cwd would render as an absurd label
    return "/".join(parts[-2:])


def _project_identity_key(prefix: str, path: str) -> str:
    canonical = os.path.normcase(os.path.realpath(path))
    digest = hashlib.blake2b(canonical.encode("utf-8", "surrogatepass"), digest_size=12)
    return f"{prefix}{digest.hexdigest()}"


def _git_checkout(cwd: str) -> tuple[str | None, str | None]:
    """The checkout holding ``cwd`` and the main repository root it belongs to.

    The two differ only in a linked worktree, which is how a caller tells one.
    """
    cursor = os.path.realpath(cwd)
    repo_root: str | None = None
    git_dir: str | None = None
    for _ in range(64):
        marker = os.path.join(cursor, ".git")
        if os.path.isdir(marker):
            repo_root, git_dir = cursor, marker
            break
        if os.path.isfile(marker):
            try:
                with open(marker, encoding="utf-8", errors="replace") as handle:
                    pointer = handle.read(4096)
            except OSError:
                pointer = ""
            prefix, separator, value = pointer.partition(":")
            if separator and prefix.strip().casefold() == "gitdir" and value.strip():
                repo_root = cursor
                git_dir = os.path.realpath(os.path.join(cursor, value.strip()))
            break
        parent = os.path.dirname(cursor)
        if parent == cursor:
            break
        cursor = parent
    if not git_dir:
        return repo_root, repo_root
    common_file = os.path.join(git_dir, "commondir")
    try:
        with open(common_file, encoding="utf-8", errors="replace") as handle:
            common = handle.read(4096).strip()
    except OSError:
        common = ""
    if not common:
        return repo_root, repo_root
    common_dir = os.path.realpath(os.path.join(git_dir, common))
    main = os.path.dirname(common_dir) if os.path.basename(common_dir) == ".git" else repo_root
    return repo_root, main


def _git_identity_root(cwd: str) -> str | None:
    return _git_checkout(cwd)[1]


def project_root(cwd: str) -> str | None:
    """Canonical project root for a measured absolute working directory."""
    if not cwd or not os.path.isabs(cwd):
        return None
    canonical = os.path.realpath(cwd)
    if not os.path.isdir(canonical):
        return None
    return _git_identity_root(canonical) or canonical


def checkout_root(cwd: str) -> str | None:
    """The toplevel of the checkout holding a measured working directory.

    Unlike `project_root`, a linked worktree is its own root here: a relative script runs from
    the checkout it sits in, and the main checkout's copy is a different file.
    """
    if not cwd or not os.path.isabs(cwd):
        return None
    canonical = os.path.realpath(cwd)
    if not os.path.isdir(canonical):
        return None
    return _git_checkout(canonical)[0] or canonical


def project_identity(config: RuntimeConfig, cwd: str) -> dict[str, str]:
    """Stable local project key and basename from a measured working directory.

    A linked worktree's ``.git`` file points at a per-worktree gitdir whose
    ``commondir`` points back to the main checkout's ``.git``. Following those
    two bounded plaintext pointers makes the main checkout and every worktree
    one project without invoking Git during collection. The key is a digest of
    that canonical root: unrelated repositories with the same basename remain
    distinct without publishing an absolute path.

    A non-Git directory has no stronger identity source. It gets a path-derived
    key and its own basename; callers retain their existing display fallback if
    the cwd is unusable.
    """
    if not cwd or not os.path.isabs(cwd):
        return {}
    return _identity_from_root(config, cwd, _git_identity_root(cwd))


def _identity_from_root(config: RuntimeConfig, cwd: str, repo_root: str | None) -> dict[str, str]:
    if not os.path.isdir(os.path.realpath(cwd)):
        return {}
    root = repo_root or os.path.realpath(cwd)
    name = os.path.basename(root.rstrip(os.sep)) or project_from_cwd(config, root)
    return {
        "key": _project_identity_key("git:" if repo_root else "path:", root),
        "name": name,
        "source": "git common directory" if repo_root else "working directory path",
    }


def _removed_worktree(cwd: str) -> tuple[str, str] | None:
    """``(repository root, worktree name)`` for a path under a deleted linked worktree.

    The ``.git`` pointers are gone with the directory, so the only evidence is the
    ``<root>/.claude/worktrees/<name>`` layout Claude Code creates, and it counts
    only when ``<root>`` still holds a ``.git`` directory. Other harnesses' layouts
    are not guessed at, per
    [D-7](docs/design-session-identity.md#d-7-a-session-in-a-linked-worktree-files-under-its-repository).
    """
    parts = cwd.split(os.sep)
    for index in range(len(parts) - 3, 0, -1):
        if parts[index : index + 2] == [".claude", "worktrees"] and parts[index + 2]:
            root = os.sep.join(parts[:index]) or os.sep
            if os.path.isdir(os.path.join(root, ".git")):
                return os.path.realpath(root), parts[index + 2]
            return None
    return None


def apply_project_identity(config: RuntimeConfig, session: Session, cwd: str) -> None:
    """Attach a measured hidden key and short name without replacing legacy display data."""
    if not cwd or not os.path.isabs(cwd):
        return
    # One read serves the key, the label and the worktree name, per
    # [D-7](docs/design-session-identity.md#d-7-a-session-in-a-linked-worktree-files-under-its-repository).  # noqa: E501
    checkout, main = _git_checkout(cwd)
    identity = _identity_from_root(config, cwd, main)
    if not identity:
        removed = _removed_worktree(cwd)
        if removed:
            root, name = removed
            label = project_from_cwd(config, root)
            if label:
                session["project"] = label
                session["project_key"] = _project_identity_key("git:", root)
                session["project_name"] = os.path.basename(root) or label
                session["project_identity_source"] = "git common directory"
                session["worktree"] = name
        return
    session["project_key"] = identity["key"]
    session["project_name"] = identity["name"]
    session["project_identity_source"] = identity["source"]
    if checkout and main and checkout != main:
        # The label is what the board groups on, so a linked worktree files under
        # its repository and the checkout's own name moves to `worktree`, which
        # keeps two sessions on one repository distinguishable (DRC-4932).
        label = project_from_cwd(config, main)
        if label:
            session["project"] = label
            session["project_key"] = identity["key"]
        session["worktree"] = os.path.basename(checkout.rstrip(os.sep)) or None


def fmt_duration(seconds: float | None) -> str:
    if seconds is None or seconds < 0:
        return "–"
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m"
    if seconds < 86400:
        return f"{seconds // 3600}h {(seconds % 3600) // 60}m"
    return f"{seconds // 86400}d {(seconds % 86400) // 3600}h"


def age(config: RuntimeConfig, now: float, timestamp: float) -> float | None:
    """Seconds since ``timestamp``; ``None`` when the timestamp is implausible.

    A timestamp far in the future is not activity. It arrives from a store
    restored from backup, a file copied across the WSL boundary with its original
    mtime, or a guest whose clock drifted while the host was suspended. Read as
    an ordinary age, ``now - timestamp`` goes negative and satisfies *every*
    ``<= threshold`` comparison built on it — so the session reads Working, and
    keeps reading Working, for as long as the skew lasts. A clock a day ahead
    buys a day of phantom activity and phantom output tokens.

    Note that merely clamping the result at zero does not help: zero reads as
    "just now", which is still fresh. An implausible timestamp has to be
    rejected outright so no activity is invented from it. Overshoots within
    ``config.future_skew_tolerance_sec`` are clamped instead of rejected, because
    at that scale they are sampling noise — ``stat()`` and the collection clock
    are read microseconds apart, and coarse filesystems (FAT's two-second write
    time, some network mounts) round upward.
    """
    if timestamp - now > config.future_skew_tolerance_sec:
        return None
    return max(0.0, now - timestamp)


def is_fresh(config: RuntimeConfig, now: float, timestamp: float, window_sec: float) -> bool:
    """Whether ``timestamp`` is a plausible time within ``window_sec`` of now."""
    seconds = age(config, now, timestamp)
    return seconds is not None and seconds <= window_sec


def reset_fields(now: float, epoch: float) -> dict[str, Any]:
    """Both forms of one reset stamp, so they cannot drift apart.

    `reset` is the wall-clock words and `resetAt` is the instant. The page shows
    a countdown built from `resetAt` and keeps the words for the tooltip: "Thu
    02:00" answers "when", but the question a quota window actually raises is
    "how long until I get it back", and the reader should not have to subtract.
    Sending the instant rather than a server-rendered countdown also keeps the
    figure true between polls instead of ageing by up to the poll interval.
    """
    return {"reset": format_reset(now, epoch), "resetAt": int(epoch)}


def format_reset(now: float, epoch: float) -> str:
    """Short local-time reset text for a quota window.

    Today reads as "14:00", within the coming week as "Thu 09:00", and anything
    further out as a date, because a weekly window can reset up to seven days
    away and an hour-of-day alone would name the wrong day.
    """
    then = datetime.fromtimestamp(epoch, tz=UTC).astimezone()
    ref = datetime.fromtimestamp(now, tz=UTC).astimezone()
    if then.date() == ref.date():
        return then.strftime("%H:%M")
    if 0 <= (then - ref).total_seconds() < 7 * 86400:
        return then.strftime("%a %H:%M")
    return then.strftime("%b %d")


def newest_plausible(config: RuntimeConfig, now: float, timestamps: Iterable[float]) -> float:
    """Newest timestamp that is not implausibly ahead of ``now``; 0 if none.

    Every activity decision goes through this rather than ``max()``. ``max()``
    picks the *implausible* value — a future timestamp is by definition the
    largest — so rejecting it afterwards throws away the good evidence too, and
    a transcript being written right now but holding one clock-skewed record
    reads Idle. That is the opposite of what rejecting future timestamps is
    for. It also matters for display (a skewed value renders as "–") and for
    de-duplication, where it would beat a perfectly good copy of the session.

    Callers then test the result with ``is_fresh()``: freshness is monotonic in
    the timestamp, so checking the newest plausible source is equivalent to
    checking them all, at half the work on every five-second refresh.
    """
    return max((t for t in timestamps if age(config, now, t) is not None), default=0.0)


# How much of a vendor's model string a session row may carry. Model names are
# untrusted vendor text on their way to the DOM, and a row's model sits inline in
# a metadata line beside the project and the session id, so an unbounded value
# pushes everything after it off the card.
#
# `quota.MODEL_LABEL_CAP_CHARS` is also 40 and this is deliberately not it.
# `quota.py` imports this module, so importing back is a cycle — but the reason
# they are two symbols is not the cycle. Quota's cap is an input to a
# distinctness requirement: a per-model usage row that elides has to keep a
# digest so two long names that share a prefix stay two rows. A session row has
# no such requirement — one row, one model, nothing to tell apart — so it just
# truncates. The numbers agree by coincidence of purpose, not by dependency, and
# either may move without the other.
MODEL_CAP_CHARS = 40

# Wider than the model cap because the long case here is an MCP tool's wire name
# — a `mcp` + server + tool triple joined by double underscores, 33 characters
# for `mcp__claude_ai_Linear__save_issue` and longer for a nested server. The
# page rewrites those to "server · tool name" at the render site, so truncating
# them to 40 here would cut the half that says which tool ran.
TOOL_NAME_CAP_CHARS = 60

# A final answer is useful as session context, but it is transcript-authored
# text crossing into the dashboard payload. Four KiB preserves ordinary
# Markdown answers while keeping one pathological response from dominating a
# poll or an expanded project strip.
LAST_OUTPUT_CAP_CHARS = 4096

# The maximum number of subagents published in a session's roster. Capping
# prevents long-running swarms with hundreds of finished workers from bloating
# payload size and degrading browser performance. Live workers are retained
# first, followed by the most recent finished workers; `subagents_omitted`
# reports how many were left out.
SUBAGENTS_ROSTER_CAP: Final = 60


def cap_subagents_roster(
    roster: list[dict[str, Any]],
    cap: int = SUBAGENTS_ROSTER_CAP,
) -> tuple[list[dict[str, Any]], int]:
    """Order and cap a subagents roster, retaining live workers first.

    Live entries (active is True) outrank finished entries. Finished entries
    are ordered newest-first by started_at. When the roster exceeds the cap,
    the excess is sliced from the oldest finished workers and reported as the
    omitted count.
    """
    live = [r for r in roster if r.get("active") is True]
    finished = [r for r in roster if r.get("active") is not True]
    finished.sort(key=lambda r: float(r.get("started_at") or 0), reverse=True)
    ordered = live + finished
    if len(ordered) > cap:
        return ordered[:cap], len(ordered) - cap
    return ordered, 0


# The readings a collector may disclose it could not take from a store that
# opened. Named constants and not literals at each site: this text reaches the
# screen verbatim, and five collectors spelling the same reading five ways would
# render as five different facts. Each is phrased to complete the page's
# sentence, "Source not fully read: …".
UNREAD_BLOCK: Final = "block state"
UNREAD_HISTORY: Final = "message history"
UNREAD_IDENTITY: Final = "session metadata"
UNREAD_MODEL: Final = "model"
UNREAD_TOKENS: Final = "token accounting"


# The shape a session id must have before it may be published as `resume_id`.
#
# It is a grammar rather than an escaper because of where the value ends up: the
# page builds `claude --resume <token>` out of it and puts that on a clipboard,
# so the exposure is everything the reader's shell and the harness's own argument
# parser will do with it. The id comes off a filename in a store the harness owns,
# which makes it untrusted like every other reading here. Sixty-four characters
# covers a UUID with room to spare and nothing near a path.
#
# The first character is deliberately narrower than the rest, and that is the half
# quoting would not have bought. A token a shell reads as one word can still be a
# word the CLI reads as a flag: `claude --resume` takes an OPTIONAL value, so it
# never consumes a `-`-leading next token, and clap binds one to an option rather
# than to Codex's positional. `--dangerously-skip-permissions` as a stem would
# therefore be pasted as a permission bypass with the session id silently dropped.
# No real id starts with a dash — both harnesses' ids are UUIDs.
RESUME_TOKEN_PATTERN: Final[re.Pattern[str]] = re.compile(r"\A[A-Za-z0-9_][A-Za-z0-9_-]{0,63}\Z")


def resume_token(value: Any) -> str | None:
    """Return ``value`` when it is a session id safe to build a command from."""
    if not isinstance(value, str):
        return None
    return value if RESUME_TOKEN_PATTERN.match(value) else None


def base_session(harness: str, sid: Any, project: str) -> Session:
    # "session" is the display id. The 8 below is the floor and must match
    # config.display_id_len, which assign_display_ids() reads; nothing enforces
    # that they agree. assign_display_ids() widens it per (harness, project)
    # group where that floor collides. "sid" keeps the full identity so the client
    # can key per-session state without truncation collisions (e.g. two Gemini
    # "session-*" fallback ids are one string apart at the floor). Claude passes
    # its 8-char prefix, already its key upstream, so sid == session there.
    # `provider` and `model` are the authority a session is spending and the
    # model it is spending it on. Declared here for every harness, at None, so
    # the payload's shape does not depend on which collector filled a row: a key
    # that appears only for some harnesses makes every consumer test for
    # presence rather than for a value.
    #
    # `provider` is Pi's alone, because Pi is the one harness with no authority
    # of its own and therefore the one where the answer is not already the
    # harness name. It is the vendor's own id, unmapped (`openai-codex`, not
    # `codex`). Naming is presentation and belongs to the page, which has the
    # harness table; the payload stays the raw reading.
    #
    # `model` is not Pi's alone. Claude, Codex, Copilot, Antigravity, Cursor and
    # OpenCode each record the model somewhere their collector already reads, so
    # each fills it; Gemini, Goose and Droid leave it None because nobody has
    # found where — or whether — those harnesses record it. Cursor fills it
    # on a child as well as on the parent, out of the child's own store: each
    # Cursor subagent keeps one, so the reading is the same read done twice
    # rather than a parent's model attributed downwards.
    #
    # None therefore means "not read", never "no model". Every session runs on
    # some model, so an absent value is a gap in our reading rather than a fact
    # about the world, and that is why the page draws it as an explicit dash with
    # a tooltip naming the harness instead of leaving the slot blank. A blank
    # slot and a measurement are indistinguishable, which is the collapse this
    # field exists to avoid. Bounded to MODEL_CAP_CHARS at the collector, through
    # `records.safe_text`: the value is untrusted vendor text.
    #
    # A collector must never infer it — not from a plan name, a token count, a
    # timestamp join, or which quota bucket moved. A guessed model renders
    # identically to a measured one.
    #
    # `consumption` is what the session has spent, and it is declared here for
    # the same reason as those two: only Copilot fills it, because Copilot is the
    # one harness that keeps a per-request billing ledger beside its sessions.
    # It carries its own unit as text ("16.61 AIU"), because a bare number is not
    # comparable across harnesses — AIU, tokens and dollars are three different
    # quantities, and a naked `consumption: 16.61` invites one axis through all
    # of them. Text also matches the harness usage tile's `used`, so a reader
    # checking a row against the tile beside it compares like with like.
    #
    # None and "0.00 AIU" are different readings and both are published: no
    # accounting for this session at all, versus a ledger that covers the window
    # and records nothing against it. A collector that cannot tell those apart
    # leaves None. The window is the payload's own `window_hours`, the same span
    # the tile sums, so a row and the tile cannot disagree about one session.
    return {
        "session": str(sid)[:8],
        "sid": str(sid),
        "harness": harness,
        "project": project,
        "project_key": project,
        "project_name": project.rsplit("/", 1)[-1] or project,
        "project_identity_source": "collector project label",
        # The linked worktree's directory name; None for a main checkout, so a
        # reader of the row can tell "not a worktree" from an empty name.
        "worktree": None,
        "provider": None,
        "model": None,
        "consumption": None,
        "title": None,
        "last_prompt": "",
        "prompt_states_work": False,
        "prompt_at": None,
        "first_prompt": "",
        "first_prompt_at": None,
        "first_prompt_control": False,
        # The `/goal` a Claude Code session holds, `{"text", "at"}`, or None. None is also what a
        # session from before `/goal` publishes, so absence reads the same as "never set one".
        "session_goal": None,
        # How the goal above ended, when the transcript showed it: `{"at"}` for a clear and
        # `{"at", "reason"}` for the harness giving up. None is "not seen", never "did not
        # happen", and the goal stays None either way.
        "session_goal_cleared": None,
        "session_goal_gave_up": None,
        "last_output": None,
        # The second line beneath the title. A mapping of label, text and at, or
        # None. The label is one of "asked", "agent" or "earlier", and the page
        # renders it with the age of the stamp in front of the text.
        #
        # A key of its own rather than a wider `last_prompt`, and the reason is
        # not tidiness: `last_prompt` is read at ten render sites, two of which
        # are not the session card — the Projects page puts it FIRST in its own
        # chain and another surface renders it as a standalone line — so a labelled
        # "earlier, 40m: …" packed into it would leak onto both surfaces with no
        # label to explain it. `records.safe_text` also collapses newlines, so
        # two lines cannot share one string field at all.
        #
        # None means no honest reading was available, which is a published fact:
        # the page renders line 1 alone, exactly as it does today. It is never a
        # guess, because the title chain is a `||` — a wrong value there masks
        # the project name permanently rather than merely misleading once.
        "instruction": None,
        "state": "idle",
        "state_detail": "awaiting your message",
        "active": False,
        "last_activity": 0,
        # `last_activity` is the whole subtree: the session, its task files, and
        # every subagent and child transcript, because a parent parked on a long
        # workflow must not age out of the window. `own_activity` is the session
        # itself and nothing below it, which is the only signal that separates
        # "the human answered and it carried on" from "a background agent is
        # writing while the human still has not answered" (DRC-4097). Zero means
        # the collector does not report it, and the overlay reducer then leaves a
        # wait standing rather than guessing.
        "own_activity": 0,
        # What retires an observed stop or end, when it is narrower than
        # `last_activity`: Claude's subtree with the parent transcript read by
        # its newest conversation record rather than its mtime (DRC-4770).
        # None means the collector does not report it, and the reducer then
        # reads `last_activity` as before; never 0, which would read as a
        # measured "nothing wrote" and keep every stop forever.
        "work_activity": None,
        # The first timestamp in the session transcript, but only when this
        # process scanned from byte zero. None means the source is unmeasured;
        # a bounded tail or rebuilt oversized cache entry may not substitute
        # its own first record because that would move the start forward.
        "started_at": None,
        # When this session's turn was last observed to stop, which is the only
        # thing that separates the two situations Idle covers: a turn that ended
        # and nobody read, and a session still waiting on a reply that never came
        # (DRC-4035). None means "no stop observed" and never "did not finish" —
        # only the four harnesses in events.IDENTITY_NORMALIZERS can supply one,
        # and no collector may infer it, for the reason `model` above may not: a
        # guessed completion renders identically to a measured one. A row that
        # cannot ever carry it says so through `acquisition` below, and the page
        # prints that on the row rather than leaving the reader to infer it
        # (docs/design-scan-only-rows.md).
        "finished_at": None,
        # The turn stop Claude Code's own transcript records (its top-level
        # `stop_hook_summary`), set by the Claude collector only from that
        # record and only while nothing has come after it (owner, 2026-10-02).
        # It is the transcript's recorded stop and never an observation:
        # `finished_at` above stays hook-only, and `reading.observed_stop` is
        # the one place the two are read together. None means no such record
        # stands, never "did not finish".
        "turn_end_at": None,
        "summary": None,
        "delegated_launches": None,
        "delegated_unpaired": None,
        "delegated_latest_launch_at": None,
        "delegated_last_activity_at": None,
        "delegated_quiet_since": None,
        "delegated_visibility": "not-recorded",
        # How this row was reached, which is the qualifier on `finished_at`
        # above. None means the harness has an event adapter and no event has
        # landed on this row; `events.ACQUISITION_EVENT` means one has;
        # `events.ACQUISITION_SCAN` means no event can ever reach it, because the
        # harness is absent from `events.IDENTITY_NORMALIZERS`. That third value
        # is stamped by `Application._mark_unreachable_by_events`, not here.
        #
        # Declared here at None for the same reason `provider` and `model` are:
        # it arrives for six of the ten harnesses, and a key present on only some
        # rows makes every consumer test for presence rather than for a value. It
        # went undeclared until the declared-field-set check reached a published
        # row rather than this function's return value (DRC-4473).
        # What the reader typed this session should achieve, and what they
        # typed it should produce. Declared here so every constructed row
        # carries the keys, and left empty here for the reason the two fields
        # below are: this module has no runtime imports and is not going to
        # gain one for a default. Every published row goes through
        # `Application._attach_annotations`, which fills all eight from
        # `annotations.published(...)` — the stored revision, or the absence
        # and its reason. A blank reaching a reader is what the board's first
        # rule forbids, and the payload field-set test is what proves one does
        # not (DRC-4508).
        #
        # Flat, not one nested mapping, and the reason is the history store
        # rather than the page. DEC-15b admits an outcome baseline into session
        # history one NAMED field at a time, and `history.PROMPT_TEXT_ALLOWLIST`
        # is a tuple of field names: it cannot say "the goal inside this dict
        # but not the rest of it". A nested carrier is also exactly the shape
        # `test_history` bans for `tasks`, `subagents` and `spacedock`. One
        # helper in the bundle rebuilds the object the renderers read, so the
        # page paid for this once.
        "annotation_goal": "",
        "annotation_goal_why": "",
        # The expected outcome's lines, one flat triple per slot, all six
        # declared (item 3 of the ruling `reading.MAX_OUTCOME_LINES` cites), and
        # the absence sentence for the list.
        "annotation_lines_why": "",
        "annotation_line_1": "",
        "annotation_line_1_source": None,
        "annotation_line_1_source_id": "",
        "annotation_line_2": "",
        "annotation_line_2_source": None,
        "annotation_line_2_source_id": "",
        "annotation_line_3": "",
        "annotation_line_3_source": None,
        "annotation_line_3_source_id": "",
        "annotation_line_4": "",
        "annotation_line_4_source": None,
        "annotation_line_4_source_id": "",
        "annotation_line_5": "",
        "annotation_line_5_source": None,
        "annotation_line_5_source_id": "",
        "annotation_line_6": "",
        "annotation_line_6_source": None,
        "annotation_line_6_source_id": "",
        "annotation_revision": None,
        "annotation_revision_count": 0,
        "annotation_at": None,
        "annotation_goal_source": None,
        "annotation_goal_source_at": None,
        "annotation_goal_saved_at": None,
        "annotation_window_start": None,
        "annotation_binding_why": "",
        # The third answer a discard made possible (DRC-4565). None on every
        # row nothing was discarded on, which is what the two states above
        # cannot say between them: `annotation_revision_count` is 0 both for a
        # session nobody typed against and for one whose words a reader
        # deleted, and the sentences beside it read alike.
        "annotation_discarded_at": None,
        "annotation_discarded_why": "",
        # The reader's answer to "does a later direction change what you asked
        # for", as three scalars: when they answered, what they answered
        # through, and the revision it rested on. None is nobody having
        # answered, which is the ordinary case and not an error.
        "annotation_settled_at": None,
        "annotation_settled_through": None,
        "annotation_settled_revision": None,
        # A reading of this session against those words, the number of presses
        # that reached the model, and the reason there is no reading. Declared
        # here at their absent values on the rule above: a missing key renders
        # as `undefined`, and an absence has to arrive carrying its reason.
        "annotation_assessment": None,
        "annotation_reading_count": 0,
        "annotation_reading_withheld": "",
        "annotation_reading_withheld_at": None,
        "annotation_reading_refused": False,
        # Whether a press could start a reading now, `{ok, reason, until}`
        # from `reading.press_eligibility`, filled by
        # `aggregate._attach_annotations`. None is not computed (annotations
        # off), which is a different reading from `{"ok": False}`. Nested, and
        # never in session history, for the reason `delivery_departure` gives.
        "reading_eligibility": None,
        # The reader's Not accurate mark on that reading (DRC-4695): a bool,
        # never sent, never counted and never in session history.
        "annotation_not_accurate": False,
        # Departures earlier readings found that the readings since no longer find, each
        # `{key, read_at, revision_read, criterion}`. `[]` is every row with none: a list to
        # render, never a count. Model prose, so never in session history.
        "annotation_prior_departures": [],
        # The messages in this session recognised as a correction the reader
        # copied from Compass, each `{"fact_id", "at"}` (DRC-4678). `[]` is
        # every row with none, which is also every row nothing was copied for:
        # it is a list to read, never a count. Filled by
        # `copied_corrections.attach`, and never in session history.
        "copied_prompts": [],
        # What became of the notifications raised about this session, and
        # whether a dashboard tab has reported a notification lane of its own.
        # Declared here at their absent values on the rule above, and left empty
        # here for the same reason: this module has no runtime imports.
        # `Application._delivery_fields` fills all nine from
        # `deliveries.published(...)`, which owns every sentence.
        #
        # The browser lane is board-wide rather than per session, and rides on
        # the row anyway: its sentence is relative to the raise it sits beside,
        # and one top-level sentence could not carry that gap.
        "delivery_outcome": "",
        "delivery_why": "",
        # The absence of a raise, said out loud. Only ever printed beside a
        # departure: silence there reads as a raise the reader ignored, and a
        # session nobody was raised about still draws no panel at all.
        "delivery_none_why": "",
        "delivery_at": None,
        "delivery_raises": 0,
        "delivery_mixed": False,
        "delivery_mixed_why": "",
        "delivery_binding_why": "",
        # The same set again, narrowed to the lane that raises a departure. A
        # sentence printed BESIDE a departure may not come from the flat keys
        # above: those carry the latest raise of any of the four lanes that
        # write the store, so an unrelated hook refusal spoke for a departure
        # that had been handed over. Nested rather than seven more flat names,
        # and never in session history, so the flat-fields rule above does not
        # reach it. `None` is a payload that carries no delivery scope at all.
        "delivery_departure": None,
        "browser_lane": False,
        "browser_lane_at": None,
        "browser_lane_why": "",
        # What the unasked reading lane raised about this session, and why there
        # is nothing. Declared here at their absent values on the rule above;
        # `Application._unasked_fields` fills all three from `unasked.published`,
        # which is where the four sentences live so an exhausted cap cannot read
        # like a session found to be on track.
        "departures": [],
        "departure_why": "",
        # Whether this session has ever been read against the words it holds
        # now, which is what makes the list above a measurement. `[]` is the
        # value on a session the lane never reached AND on one it read and
        # found nothing in, so a count of that list is a number in one case and
        # an absence in the other: a review surface printed "Departures the
        # checks run while you were away raised 0" under "Compass has not
        # checked this session against what you asked for".
        #
        # "the words it holds now" is load bearing and was not kept: a check
        # outlives the words it read, so an entry blanked by the board's
        # `clear` plus the save after it left this True with nothing typed
        # against the session (DRC-4560). `unasked.published` now reads the
        # annotation entries for that half.
        "departure_checked": False,
        "acquisition": None,
        # When the standing wait began, for the row_order gate queue and the
        # waited-for duration the page prints. Only the Claude, Copilot and
        # Cursor collectors and the event overlays ever fill it; declared here at
        # None on the rule above, and because it is in `events.PATCHABLE`, which
        # means an untrusted envelope can write it onto any row.
        "blocked_since": None,
        # Whether a repeating-source wait has exceeded its 300-second evidence
        # lease without a fresh positive observation. Declared here at False,
        # and in `events.PATCHABLE` so the overlay reducer can patch it.
        "wait_unconfirmed": False,
        # When this session id was observed to END, which is a different fact
        # from `finished_at` above: that one marks a TURN stopping, and a session
        # whose turn stopped is usually still open and typeable. Without this the
        # two render identically — both say Idle — and the reader cannot tell a
        # session that is over from one sitting at its prompt waiting for them
        # (DRC-4036).
        #
        # None means NOT OBSERVED and never "did not end", which is the whole
        # reason this is nullable rather than a boolean or a fourth `state`
        # value. Only a SIGKILL ends a Claude session silently — a SIGTERM and
        # a closed terminal delivered `SessionEnd` within 0.687s, and both clean
        # exits delivered one too, the headless completion slowest at 5.581s
        # (docs/captures/claude/session-end-2.1.261-macos.jsonl) — but an
        # absent end still covers the six harnesses with no event adapter, a
        # session that ended before any run of this board recorded it (an end a
        # previous run did record survives the restart, DRC-4547), and
        # `--no-events`. A boolean here
        # would do null's job with false, which is the DRC-4101 failure the
        # comments above and `events.py` both name.
        #
        # `/clear` is not the exception it looks like. It emits `SessionEnd` and
        # the process keeps accepting prompts, but the prompt after it goes to a
        # NEW session id: measured 2026-09-06 on Claude Code 2.1.261, two prompts
        # either side of one `/clear` wrote two different transcripts. So the id
        # this mark is attached to really is finished, whatever the reason was,
        # and no collector or adapter needs to read `reason` to know it.
        "ended_at": None,
        # What one end-of-session `git status` observed in this session's working
        # repository, or None for both. None means NOT PROBED and never "clean":
        # only a harness whose adapter maps a session-end event can be probed at
        # all, and `--no-git`, a directory that is not a repository, an event with
        # no `cwd`, git absent from PATH and a timed-out probe all land here too.
        # Defaulting `dirty` to False instead would publish a confident clean over
        # no evidence on almost every row — the DRC-4101 failure, one field over.
        # `changed` counts porcelain ENTRIES, not files: git collapses an untracked
        # directory into one entry, so every rendering must say entries.
        "dirty": None,
        "changed": None,
        # Whether this run holds a terminal a focus command could name. A BIT and
        # never the target: SECURITY.md's focus section forbids echoing one, and
        # what a page needs is only enough to render nothing dead. False covers
        # the feature being off, a harness with no adapter, a session that
        # predates this server run, a session running outside tmux, and a
        # platform with no named case — Linux and Windows, where the section's
        # own device grammar refuses `/dev/pts/N` and so no raise could ever
        # succeed. A control that does nothing is what that False prevents.
        "focusable": False,
        "command_reports": None,
        "rate_per_min": 0,
        # Output-token readings from the transcript scanner. The session count
        # is present only after a byte-zero scan; the turn count only after that
        # turn's opening boundary was observed. None is incomplete or unmeasured,
        # including every harness without a reviewed usage record shape.
        "session_output_tokens": None,
        "turn_output_tokens": None,
        "total": 0,
        "done": 0,
        "open": 0,
        "progress_pct": 0,
        "eta_h": None,
        "turn": None,
        # `{"errors": int, "tool": str | None}` where a run of failed tool calls
        # was measured inside the current turn, else None. Top-level rather than
        # a key on `turn`, because `turn_progress` publishes nothing for a
        # session that is not working: riding on `turn` would delete the flag the
        # moment the loop stopped, which is exactly when the human walks back to
        # the machine. It is cleared at the next prompt instead — by then they
        # have seen it. Claude only, since Claude is the only harness that
        # records whether a tool call failed (see records.tool_outcome).
        "loop": None,
        # The token this harness's own CLI takes to re-enter this session, or None
        # where there is nothing honest to publish. It exists because `sid` is not
        # that token everywhere: Claude's `sid` is the eight-character transcript
        # prefix, which is its key upstream, and `claude --resume 27d10654` answers
        # "not a UUID and does not match any session title" (measured on 2.1.261).
        # Codex's `sid` already is the id `codex resume` takes and it is repeated
        # here rather than special-cased in the page, so the page's rule can be
        # total: no token, no control.
        #
        # None is the declared value and no collector may infer one. A guessed
        # command reads exactly like a measured one and fails in the reader's
        # terminal rather than here. It passes `resume_token` on the way out, for
        # the reason that function gives.
        "resume_id": None,
        # One element per subagent, carrying `name` (str), `model` (str | None),
        # `started_at` (float | None), `active` (bool | None) and `parent`
        # (str | None). Every measurement key is always present. None means not
        # read, never "same as the parent" for model or "started with the
        # parent" for time. A child start comes from its own transcript; mtime
        # is last activity and cannot stand in for it.
        #
        # `active` is this element's own liveness and `parent` the member that
        # spawned it, both added by DRC-4344 for teammates dispatched into their
        # own panes. Claude measures them; every other collector publishes None
        # on both, which says its liveness and parentage are unread rather than
        # that the child is idle and parentless. The frontend therefore treats
        # None as live, so a harness nobody has taught to measure this renders
        # exactly as it did before. Only `False` withholds the pulse and the
        # running count.
        #
        # Model is a key rather than a parallel list of only the children whose
        # model differs, because absence from such a map would mean either
        # "matches the parent" or "not measured", which collapses in the wire
        # format the exact two facts this field is here to keep apart. It is also
        # a key rather than a suffix on `name`, because a subagent genuinely named
        # `foo · gpt-5` would then be indistinguishable from a measurement.
        #
        # There is no join key to offer instead: labels are non-unique by
        # construction (several collectors fall back to a bare "subagent"), so two
        # unnamed children collide and a model gets attributed to a sibling.
        #
        # The page shows a child's model only where the child's and the parent's
        # are both measured and unequal. That rule lives in one place, in the
        # frontend, because both views need it and a re-derivation is how they
        # would come to disagree.
        "subagents": [],
        "subagents_omitted": 0,
        "subagent_hierarchy": None,
        "subagent_events": None,
        "tasks": [],
        "spacedock": None,
        "cached_deterministic_goal": None,
        # The readings this row's collector could not take from a store it
        # opened, by name, from the `UNREAD_*` vocabulary above. Empty is "no
        # unread reading reported" and never "the store held nothing".
        #
        # It exists because the fourth state of a store read — opened, and
        # nothing in it recognised — was silent on every surface. The good
        # fields survive that, which is the whole reason it cannot be routed
        # through `io.record_store_error`: that would withdraw a title and a
        # workspace that were correct, and `cursor.py`'s `_meta` records the
        # measurement behind refusing to. Nor does the error record help, because
        # it reaches no reader: `state.store_errors` is read only by
        # `diagnostics.diagnose`, appears in no `/api/data` key, and is named
        # nowhere under `web/`. So a published field is the only way this fact
        # reaches a screen, whichever way the error boundary is drawn.
        #
        # The reader's version of the problem is sharper than a missing value:
        # a row whose store told us nothing renders as a session at its prompt
        # when its mtime is stale, and as one *generating* when its mtime is
        # fresh. Both are confident claims over an absence.
        #
        # A list of names rather than a boolean, because "something could not be
        # read" is not actionable and because a bare False would then mean both
        # "nothing failed" and "this collector never looks".
        "source_gaps": [],
    }


def dedupe_sessions(sessions: list[Session]) -> list[Session]:
    """Collapse sessions found in more than one candidate store.

    Scanning every candidate root means a session left behind by a migration
    can be discovered twice. Most collectors key by session id internally and
    merge naturally, but the database-backed ones append per store — so the
    same id produced two rows and counted its tokens twice in the summary.
    The freshest copy wins.
    """
    best: dict[tuple[str, str], Session] = {}
    for session in sessions:
        key = (str(session["harness"]), str(session["sid"]))
        current = best.get(key)
        if current is None or session["last_activity"] > current["last_activity"]:
            best[key] = session
    return list(best.values())


def assign_display_ids(config: RuntimeConfig, sessions: list[Session]) -> None:
    """Widen each session's display id until it is unique among the rows it
    could be confused with.

    Codex hands out UUIDv7, whose leading 48 bits are a millisecond timestamp.
    A fan-out launched in one directory therefore shares its leading hex, and
    an 8-char display id rendered several distinct sessions as the same
    harness, project and id — one session, apparently.

    The group is ``(harness, project)`` because that is exactly what a row
    prints beside the id, so those are the rows a reader has to tell apart.
    Widening per harness instead would drag every unrelated row in that harness
    out to the width one colliding fan-out needed: four agents started in the
    same millisecond need 16 to 18 characters, and a lone session in another
    worktree would inherit that for nothing.

    Mutates ``session["session"]`` only. ``sid`` is what every caller keys on
    and is left whole.
    """
    groups: dict[tuple[str, str], list[Session]] = {}
    for session in sessions:
        groups.setdefault((str(session["harness"]), str(session["project"])), []).append(session)
    for group in groups.values():
        sids = [str(s["sid"]) for s in group]
        width = config.display_id_len
        longest = max((len(sid) for sid in sids), default=config.display_id_len)
        # Terminates: width strictly increases and is bounded by the longest
        # sid, where every prefix is the whole id. Comparing distinct prefixes
        # against distinct sids also means repeated sids cannot drive it.
        while width < longest and len({sid[:width] for sid in sids}) != len(set(sids)):
            width += 1
        for session in group:
            session["session"] = str(session["sid"])[:width]


def rate_from(info: dict[str, Any] | None, now: float, config: RuntimeConfig) -> int:
    if not info:
        return 0
    recent: float = sum(
        tok for ep, tok in info["usage_events"] if is_fresh(config, now, ep, config.rate_window_sec)
    )
    return round(recent / (config.rate_window_sec / 60))


def working_detail(info: dict[str, Any] | None, subagents: list[Any]) -> str:
    if subagents:
        n = len(subagents)
        return f"running {n} subagent{'s' if n > 1 else ''}"
    if info and info.get("thinking"):
        # Before `last_tool`: a collector that can see the model holding the
        # turn (no tool call in flight) must not let a tool name from an
        # earlier, completed turn relabel a thinking block as running it.
        return "thinking"
    if info and info.get("last_tool"):
        return f"running {info['last_tool']}"
    return "generating…"
