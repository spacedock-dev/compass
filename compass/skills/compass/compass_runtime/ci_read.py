"""A pull request's or merge request's CI checks, read when a reader presses Analyze.

[DEC-30](docs/design-reading-a-session.md#dec-30-compass-may-read-a-pull-requests-ci-state-when-the-reader-presses-analyze)
is the ruling and this module is its launcher. It is the one place that runs `gh` or `glab`, and it
runs one only on an admitted press, for one bound pull request, with every launch safeguard the
ruling lists: an absolute binary resolved against a PATH with no relative element, a private empty
working directory, no `GH_*`, `GITLAB_*` or `GL_*` override, an owner, repository and number checked
against a closed pattern before any subprocess, a known host only, a hard timeout that kills the
process group, JSON that is parsed whatever the exit code (`gh pr checks` exits 8 while a check is
pending and 1 while one has failed), size-capped and schema-checked, and stderr reduced to a closed
token.

What leaves this module is a plain record (`validate` is its shape) and the facts built from it
(`facts`). The record carries each check's name, bucket and completion time and nothing else the
CLI said: no description, link, log or workflow text. A check name is writable by whoever writes
the workflows, so it takes a closed character set and a clip here.

GitLab is read through `glab api` with fixed, read-only endpoints, and only on a host that glab's
own configuration already names (`glab_hosts`), read from its file before anything is launched.
A merge request is bound by its goal URL alone: whether Claude Code writes a `pr-link` for a
GitLab merge request is not measured
(`docs/captures/claude/gitlab-merge-request-read-unmeasured.md`).
A GitLab repository is stored as `host/group/.../project`, which no GitHub `owner/repo` can be,
because a GitHub owner holds no dot.

This module imports nothing from `reading`, which imports it.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
import threading
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any, Final
from urllib.parse import quote

from . import git_status, supervise
from . import io as runtime_io

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Mapping, Sequence

    from .config import RuntimeConfig

FACT_TYPE: Final = "ci_check"
FACT_SUBJECT: Final = "ci"
HOST: Final = "github.com"

BUCKET_PASS: Final = "pass"  # noqa: S105 - a bucket name, not a credential
BUCKET_FAIL: Final = "fail"
BUCKET_PENDING: Final = "pending"
BUCKET_SKIPPING: Final = "skipping"
BUCKET_CANCEL: Final = "cancel"
BUCKETS: Final = (BUCKET_PASS, BUCKET_FAIL, BUCKET_PENDING, BUCKET_SKIPPING, BUCKET_CANCEL)

SOURCE_GOAL: Final = "goal"
SOURCE_RECORD: Final = "record"
SOURCES: Final = (SOURCE_GOAL, SOURCE_RECORD)

# Why a read produced no checks, as a closed set. The page maps each to its own sentence, so no
# word of the CLI's reaches a reader through this field.
ERROR_MISSING: Final = "gh-missing"
ERROR_SIGNED_OUT: Final = "gh-signed-out"
ERROR_NOT_FOUND: Final = "pull-request-not-found"
ERROR_RATE_LIMITED: Final = "rate-limited"
ERROR_TIMEOUT: Final = "timeout"
ERROR_OUTPUT: Final = "unreadable-output"
ERROR_FAILED: Final = "gh-failed"
ERROR_GLAB_MISSING: Final = "glab-missing"
ERROR_GLAB_SIGNED_OUT: Final = "glab-signed-out"
ERROR_GLAB_FAILED: Final = "glab-failed"
# A goal URL named a GitLab host that glab's configuration does not hold: nothing is launched.
ERROR_HOST: Final = "host-not-configured"
ERRORS: Final = (
    ERROR_MISSING,
    ERROR_SIGNED_OUT,
    ERROR_NOT_FOUND,
    ERROR_RATE_LIMITED,
    ERROR_TIMEOUT,
    ERROR_OUTPUT,
    ERROR_FAILED,
    ERROR_GLAB_MISSING,
    ERROR_GLAB_SIGNED_OUT,
    ERROR_GLAB_FAILED,
    ERROR_HOST,
)

TIMEOUT_SEC: Final = 20.0
# `gh pr checks --json` prints about 250 bytes a check; a pull request with a thousand of them
# is far past anything a reading can use, and the cap is what stops a hostile endpoint filling a
# disk.
OUTPUT_LIMIT_BYTES: Final = 262_144
STDERR_LIMIT_BYTES: Final = 8_192
# Every check is counted; only this many are listed, failures first, so a long matrix cannot hide
# the one that failed and the prompt stays small.
MAX_COUNTED: Final = 1_000
MAX_LISTED: Final = 40
NAME_CAP_CHARS: Final = 80
SCAN_BYTES: Final = 16 * 1024 * 1024
MAX_SCANNED: Final = 40

_OWNER_RE = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})")
_REPO_RE = re.compile(r"[A-Za-z0-9._-]{1,100}")
_BRANCH_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,99}")
_HEAD_RE = re.compile(r"[0-9a-f]{40}")
_NUMBER_MAX = 10_000_000
_PR_URL_RE = re.compile(
    r"https://github\.com/(?P<owner>[A-Za-z0-9-]{1,39})/(?P<repo>[A-Za-z0-9._-]{1,100})"
    r"/pull/(?P<number>[1-9][0-9]{0,7})(?![0-9])",
    re.IGNORECASE,
)
_RUN_URL_RE = re.compile(
    r"https://github\.com/(?P<owner>[A-Za-z0-9-]{1,39})/(?P<repo>[A-Za-z0-9._-]{1,100})"
    r"/actions/runs/[1-9][0-9]{0,19}(?:/job/[1-9][0-9]{0,19})?",
    re.IGNORECASE,
)
# A GitLab host: dotted labels ending in a name, so a bare IPv4 address, `localhost` and a port all
# fail it. An IPv6 literal carries brackets and colons, which no label holds.
_HOST_RE = re.compile(
    r"(?=.{4,253}\Z)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z](?:[a-z0-9-]{0,61}[a-z0-9])?"
)
_GROUP_SEGMENT_RE = re.compile(r"[A-Za-z0-9_][A-Za-z0-9._-]{0,254}")
_MR_URL_RE = re.compile(
    r"https://(?P<host>[A-Za-z0-9.-]{4,253})/(?P<path>[A-Za-z0-9._/-]{3,600}?)"
    r"/-/merge_requests/(?P<number>[1-9][0-9]{0,7})(?![0-9])",
    re.IGNORECASE,
)
_GITLAB_STATUS_BUCKET: Final = {
    "success": BUCKET_PASS,
    "failed": BUCKET_FAIL,
    "canceled": BUCKET_CANCEL,
    "canceling": BUCKET_CANCEL,
    "skipped": BUCKET_SKIPPING,
    "created": BUCKET_PENDING,
    "pending": BUCKET_PENDING,
    "running": BUCKET_PENDING,
    "preparing": BUCKET_PENDING,
    "scheduled": BUCKET_PENDING,
    "waiting_for_resource": BUCKET_PENDING,
    "waiting_for_callback": BUCKET_PENDING,
}
_NAME_CHARS = re.compile(r"[^A-Za-z0-9 ._/:()+#@,\[\]-]")
_WORKFLOW_PATH = re.compile(r"(?:^|/)(?:\.github/workflows/[^/]+|\.gitlab-ci\.yml)$")
# `GLAB_CONFIG_DIR` moves the configuration the hosts check reads, and `OAUTH_TOKEN` and
# `REMOTE_ALIAS` each steer glab to another account or remote, so none reaches the child.
_REMOVED_ENV = ("GH_", "GITLAB_", "GL_", "GLAB_", "OAUTH_TOKEN", "REMOTE_ALIAS")


@dataclass(frozen=True)
class Binding:
    """The one pull request a press reads, and what bound it."""

    # `owner/repo` for GitHub, `host/group/.../project` for GitLab (`host_of` tells them apart).
    repository: str
    number: int
    source: str
    # A push names a branch and no number. The number is then looked up from the branch, once.
    branch: str = ""


def _github_repository(repository: str) -> bool:
    owner, _, repo = repository.partition("/")
    return bool(
        _OWNER_RE.fullmatch(owner)
        and _REPO_RE.fullmatch(repo)
        # `.` and `..` are path steps, not names: nothing is built from them.
        and set(repo) != {"."}
        and not repo.endswith(".git")
    )


def valid_host(host: str) -> bool:
    """Whether this is a lower case dotted host name a GitLab read may be built for, never an IP."""
    return host == host.lower() and _HOST_RE.fullmatch(host) is not None


def _gitlab_repository(repository: str) -> bool:
    host, _, path = repository.partition("/")
    segments = path.split("/")
    return (
        valid_host(host)
        and 2 <= len(segments) <= 21
        and all(
            _GROUP_SEGMENT_RE.fullmatch(segment)
            and set(segment) != {"."}
            and not segment.endswith((".git", ".atom"))
            for segment in segments
        )
    )


def valid_repository(repository: str) -> bool:
    """Whether this is a repository a launch may be built from, on either provider."""
    return _github_repository(repository) or _gitlab_repository(repository)


def host_of(repository: str) -> str:
    """The host a stored repository names: `github.com`, or the first part of a GitLab one."""
    return repository.partition("/")[0] if _gitlab_repository(repository) else HOST


def pull_request_urls(text: str) -> tuple[tuple[str, int], ...]:
    """Every distinct `(repository, number)` a text names by a pull or merge request URL."""
    found: dict[tuple[str, int], None] = {}
    for matched in _PR_URL_RE.finditer(text):
        repository = f"{matched['owner']}/{matched['repo']}"
        if _github_repository(repository) and int(matched["number"]) <= _NUMBER_MAX:
            found[(repository, int(matched["number"]))] = None
    for matched in _MR_URL_RE.finditer(text):
        repository = f"{matched['host'].lower()}/{matched['path']}"
        if (
            matched["host"].lower() != HOST
            and _gitlab_repository(repository)
            and int(matched["number"]) <= _NUMBER_MAX
        ):
            found[(repository, int(matched["number"]))] = None
    return tuple(found)


def bind(
    goal_texts: Iterable[str],
    links: Sequence[tuple[str, int]],
    pushes: Sequence[str],
    remote: tuple[str, str],
) -> Binding | None:
    """The pull request a press reads, or None.

    The goal's own URL binds, because those are the reader's words, and a goal that names two
    different pull requests binds none rather than guessing. Failing that, the newest `pr-link`
    record whose repository is the session folder's own `origin`, and failing that the newest
    pushed branch of that repository. A record naming another repository binds nothing: a
    transcript can say anything, and only the folder's own remote says it is this one. A GitLab
    merge request binds by the goal's URL alone; no record binds one, because what Claude Code
    writes for a merge request is not measured.
    """
    named = dict.fromkeys(url for text in goal_texts for url in pull_request_urls(text))
    if len(named) == 1:
        repository, number = next(iter(named))
        return Binding(repository, number, SOURCE_GOAL)
    if named:
        return None
    host, repository = remote
    if host != HOST or not _github_repository(repository):
        return None
    for linked, number in links:
        if linked.lower() == repository.lower() and 0 < number <= _NUMBER_MAX:
            return Binding(repository, number, SOURCE_RECORD)
    for branch in pushes:
        if _usable_branch(branch):
            return Binding(repository, 0, SOURCE_RECORD, branch=branch)
    return None


@dataclass(frozen=True)
class Poll:
    """What a recorded CI poll names: its repository, and the pull request or branch it reads.

    `repository` is empty when the command names none (it then reads the folder's own remote).
    `number` and `branch` are both empty when it names no pull request, which for `gh pr checks`
    means the current branch's. `valid` is False when a word it names is not one this module will
    compare, so the poll binds to nothing.
    """

    repository: str = ""
    number: int = 0
    branch: str = ""
    valid: bool = True


# Options that take a value, by command: the word after one is not the positional target.
_POLL_VALUE_FLAGS: Final = {
    "pr_checks": frozenset({"-i", "--interval", "--json", "-q", "--jq", "-t", "--template"}),
    "run_view": frozenset(
        {"-j", "--job", "-a", "--attempt", "--json", "-q", "--jq", "-t", "--template"}
    ),
}
_REPO_FLAGS: Final = ("-R", "--repo")


def _poll_repository(value: str) -> str | None:
    """`owner/repo` for a `--repo` value, or the value itself when it names another host.

    A repository on another host is kept as written so it never equals a GitHub `origin`;
    None is a value that names no repository at all.
    """
    text = value.strip()
    if "://" in text or text.startswith("git@"):
        host, repository = git_status.parse_remote(text)
        if not repository:
            return None
        return repository if host == HOST and _github_repository(repository) else text
    parts = text.split("/")
    if len(parts) == 3 and parts[0].lower() == HOST and _github_repository("/".join(parts[1:])):
        return "/".join(parts[1:])
    if len(parts) == 3 and _HOST_RE.fullmatch(parts[0].lower()):
        return text
    return text if len(parts) == 2 and _github_repository(text) else None


def _poll_operands(kind: str, rest: Sequence[str]) -> tuple[list[str], list[str]]:
    """The `--repo` values and the positional words among a poll's arguments."""
    repos: list[str] = []
    positional: list[str] = []
    value_flags = _POLL_VALUE_FLAGS[kind]
    at = 0
    while at < len(rest):
        word = rest[at]
        at += 1
        flag, equals, inline = word.partition("=")
        if word == "--":
            positional.extend(rest[at:])
            break
        if flag in _REPO_FLAGS:
            if not equals and at < len(rest):
                inline, at = rest[at], at + 1
            repos.append(inline)
        elif word.startswith("-R") and not word.startswith("--"):
            repos.append(word[2:])
        elif flag in value_flags:
            at += 0 if equals else 1
        elif not word.startswith("-"):
            positional.append(word)
    return repos, positional


# Environment names that point `gh` at another repository or host. Any word of the call that
# sets one, in the poll's own segment or an earlier one, leaves the poll bound to nothing.
_POLL_ENVIRONMENT: Final = ("GH_REPO=", "GH_HOST=", "GH_ENTERPRISE_TOKEN=")


def _ascii_number(text: str) -> bool:
    """Whether `int(text)` is safe: ASCII digits only, short of the interpreter's digit limit."""
    return text.isascii() and text.isdigit() and len(text) <= 19


def _run_view_target(positional: str, repository: str) -> Poll:
    """What a `gh run view` operand names: a run id, or a run URL carrying its own repository."""
    if not positional or (_ascii_number(positional) and 0 < int(positional) <= _NUMBER_MAX):
        return Poll(repository=repository)
    matched = _RUN_URL_RE.fullmatch(positional)
    if matched is None:
        return Poll(valid=False)
    url_repository = f"{matched['owner']}/{matched['repo']}"
    if not _github_repository(url_repository):
        return Poll(valid=False)
    if repository and repository.lower() != url_repository.lower():
        return Poll(valid=False)
    return Poll(url_repository)


def _pull_request_target(target: str, repository: str) -> Poll:
    """What a `gh pr checks` operand names: a number, a pull request URL, a branch, or nothing."""
    if not target:
        return Poll(repository=repository)
    if _ascii_number(target):
        number = int(target)
        return Poll(repository, number) if 0 < number <= _NUMBER_MAX else Poll(valid=False)
    urls = pull_request_urls(target) if target.startswith("https://") else ()
    if len(urls) == 1:
        url_repository, number = urls[0]
        if repository and repository.lower() != url_repository.lower():
            return Poll(valid=False)
        return Poll(url_repository, number)
    return Poll(repository, branch=target) if _usable_branch(target) else Poll(valid=False)


def parse_poll(
    kind: str, words: Sequence[str], raw: Sequence[str] = (), earlier: Sequence[str] = ()
) -> Poll:
    """The repository and target a `gh pr checks` or `gh run view` command names.

    `kind` is `pr_checks` or `run_view`; `words` are the program's words after any wrapper, and
    `raw` the segment's words before wrappers and assignments were stripped, so a `GH_REPO=...`
    prefix, which points `gh` at another repository, is read like `--repo`. `earlier` is every raw
    word of the call's earlier segments: one that sets `GH_REPO`, `GH_HOST` or
    `GH_ENTERPRISE_TOKEN` (an `export`, a plain assignment) leaves the poll bound to nothing, as
    does `GH_HOST` or the token on the poll itself. A variable exported in an earlier call is not
    seen.
    """
    if any(word.startswith(_POLL_ENVIRONMENT[1:]) for word in raw) or any(
        word.startswith(_POLL_ENVIRONMENT) for word in earlier
    ):
        return Poll(valid=False)
    repos, positional = _poll_operands(kind, words[3:])
    repos.extend(word.partition("=")[2] for word in raw if word.startswith("GH_REPO="))
    named = {_poll_repository(value) for value in repos}
    if len(named) > 1 or None in named or len(positional) > 1:
        return Poll(valid=False)
    repository = next(iter(named), "") or ""
    if kind == "run_view":
        return _run_view_target(positional[0] if positional else "", repository)
    return _pull_request_target(positional[0] if positional else "", repository)


def poll_bound(
    poll: Poll,
    remote: tuple[str, str],
    goal_texts: Iterable[str],
    links: Sequence[tuple[str, int]],
    pushes: Sequence[str],
) -> bool:
    """Whether a recorded CI poll reads this session's own pull request or repository.

    The poll's repository, its own or the folder's where it names none, must be the folder's
    `origin`; a poll that names a number or a branch must name one the session is bound to, by
    [DEC-30](docs/design-reading-a-session.md#dec-30-compass-may-read-a-pull-requests-ci-state-when-the-reader-presses-analyze)'s
    sources: the goal's own URL, a `pr-link` or created-pull-request record, or a pushed branch.
    A poll naming neither is the current branch's, and binds with the repository. No remote, or one
    that is not a GitHub repository, binds nothing: a recorded run cannot be checked further
    without a network call.
    """
    host, repository = remote
    if not poll.valid or host != HOST or not _github_repository(repository):
        return False
    folded = repository.lower()
    if poll.repository and poll.repository.lower() != folded:
        return False
    if poll.number:
        named = {
            number
            for text in goal_texts
            for linked, number in pull_request_urls(text)
            if linked.lower() == folded
        }
        named.update(number for linked, number in links if linked.lower() == folded)
        return poll.number in named
    if poll.branch:
        return poll.branch in pushes
    return True


def _usable_branch(branch: str) -> bool:
    return bool(
        _BRANCH_RE.fullmatch(branch)
        # A bare number is how `gh pr view` names a pull request; a branch never is one.
        and not _ascii_number(branch)
        and ".." not in branch
        and not branch.endswith((".lock", "/", "."))
    )


def scan_records(
    config: RuntimeConfig, transcript_path: str
) -> tuple[tuple[tuple[str, int], ...], tuple[str, ...]]:
    """The pull requests and pushed branches a Claude Code transcript records, newest first.

    `pr-link` rows are written on pushes to an existing pull request as well as on creation, and a
    result's structured `gitOperation.push` names the branch. Read from the transcript's tail and
    bounded in bytes and rows; neither the command nor its output is ever read.
    """
    links: dict[tuple[str, int], None] = {}
    for raw in runtime_io.reverse_lines(
        config, transcript_path, max_bytes=SCAN_BYTES, contains=b'"pr-link"'
    ):
        record = _row(raw)
        if record is None or record.get("type") != "pr-link":
            continue
        repository, number = record.get("prRepository"), record.get("prNumber")
        if (
            isinstance(repository, str)
            and _github_repository(repository)
            and type(number) is int
            and 0 < number <= _NUMBER_MAX
        ):
            links[(repository, number)] = None
        if len(links) >= MAX_SCANNED:
            break
    pushes: dict[str, None] = {}
    for raw in runtime_io.reverse_lines(
        config, transcript_path, max_bytes=SCAN_BYTES, contains=b'"gitOperation"'
    ):
        record = _row(raw)
        result = record.get("toolUseResult") if record is not None else None
        operation = result.get("gitOperation") if isinstance(result, dict) else None
        push = operation.get("push") if isinstance(operation, dict) else None
        branch = push.get("branch") if isinstance(push, dict) else None
        if isinstance(branch, str) and _usable_branch(branch):
            pushes[branch] = None
        if len(pushes) >= MAX_SCANNED:
            break
    return tuple(links), tuple(pushes)


def _row(raw: bytes) -> dict[str, Any] | None:
    try:
        value = json.loads(raw)
    except (ValueError, RecursionError):
        return None
    return value if isinstance(value, dict) else None


def changed_ci_configuration(paths: Iterable[str]) -> bool:
    """Whether any written path is a workflow file or a `.gitlab-ci.yml`."""
    return any(_WORKFLOW_PATH.search(path.strip().removeprefix("./")) for path in paths)


# --- the switches -------------------------------------------------------------------------------

SETTING_ON: Final = "on"
SETTING_OFF: Final = "off"
SETTING_FLAG: Final = "flag-off"
_OFF_MARKER: Final = "ci-read-off"


def setting(config: RuntimeConfig) -> str:
    """Whether a press may read CI: `on`, `off` (the page's setting) or `flag-off` (`--no-ci-read`).

    The page's answer is a marker file in the state directory, so it holds across restarts and
    across tabs and is the same one every dashboard of this account reads. The flag wins and the
    page cannot lift it. An unreadable state directory reads as off, because a read that cannot
    be switched off is the wrong way to fail.
    """
    if not config.ci_read_enabled:
        return SETTING_FLAG
    try:
        return SETTING_OFF if os.path.lexists(config.state_dir / _OFF_MARKER) else SETTING_ON
    except OSError:
        return SETTING_OFF


def set_setting(config: RuntimeConfig, *, on: bool) -> bool:
    """Record the page's answer. False when the flag holds it off or the state cannot be written."""
    if not config.ci_read_enabled:
        return False
    path = config.state_dir / _OFF_MARKER
    try:
        if on:
            path.unlink(missing_ok=True)
        else:
            runtime_io.atomic_write_owner_only(str(path), "off\n")
    except OSError:
        return False
    return True


# --- the launch ---------------------------------------------------------------------------------


def environment(environ: Mapping[str, str]) -> dict[str, str]:
    """The child's environment: the git probe's PATH scrub, no CLI override, no prompt, no notice.

    `GH_HOST`, `GH_REPO`, `GH_TOKEN`, `GH_CONFIG_DIR` and the `GITLAB_*` and `GL_*` names each
    redirect the CLI to another host, repository, account or configuration, so none of them
    reaches it. What the CLI then uses is the reader's own login: a `GITHUB_TOKEN` or
    `GITHUB_ENTERPRISE_TOKEN` in the environment where one is set, the stored login otherwise.
    """
    scrubbed = git_status.probe_environment(environ)
    kept = {key: value for key, value in scrubbed.items() if not key.startswith(_REMOVED_ENV)}
    kept.update(GH_PROMPT_DISABLED="1", GH_NO_UPDATE_NOTIFIER="1", NO_COLOR="1")
    return kept


def glab_environment(environ: Mapping[str, str]) -> dict[str, str]:
    """`environment` for glab: the same scrub, with glab's prompt, telemetry and update checks off.

    `GITLAB_TOKEN` applies to whatever host a command names, so a goal that names another host
    would be sent the reader's token if it survived. Stripping it means a reader who signs in to
    glab by that variable alone reads nothing, and one signed in through `glab auth login` (the
    stored login, which glab keys by host) reads normally.
    """
    kept = environment(environ)
    for key in ("GH_PROMPT_DISABLED", "GH_NO_UPDATE_NOTIFIER"):
        kept.pop(key, None)
    kept.update(NO_PROMPT="1", GLAB_SEND_TELEMETRY="false", GLAB_CHECK_UPDATE="false")
    return kept


_HOSTS_FILE_BYTES: Final = 65_536


def glab_hosts(environ: Mapping[str, str]) -> frozenset[str]:
    """The hosts glab's own configuration names, read from its file and never by launching glab.

    Only the keys under `hosts:` are read: the values hold the reader's tokens, and this reader
    never keeps one (only `api_protocol`, `api_host` and `skip_tls_verify` are read, as values to
    refuse a host that redirects the call). A host that is not a plain dotted name (an IP literal,
    one with a port) is dropped, so the set can only hold hosts a launch may name. Unreadable or
    absent is empty.
    """
    base = environ.get("XDG_CONFIG_HOME", "") or (
        environ.get("APPDATA", "")
        if os.name == "nt"
        else os.path.join(environ.get("HOME", ""), ".config")
    )
    if not base or not os.path.isabs(base):
        return frozenset()
    try:
        raw = runtime_io.read_prefix_bytes(
            os.path.join(base, "glab-cli", "config.yml"), max_bytes=_HOSTS_FILE_BYTES
        )
    except OSError:
        return frozenset()
    hosts: set[str] = set()
    redirected: set[str] = set()
    inside, depth, current = False, 0, ""
    for line in raw.decode("utf-8", "replace").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        indent = len(line) - len(line.lstrip(" "))
        if indent == 0:
            inside = stripped.rstrip() == "hosts:"
            depth = 0
            continue
        if not inside:
            continue
        depth = depth or indent
        if indent == depth and stripped.endswith(":"):
            current = stripped[:-1].strip().strip("'\"").lower()
            if valid_host(current):
                hosts.add(current)
            continue
        key, _, value = stripped.partition(":")
        key, value = key.strip(), value.strip().strip("'\"").lower()
        # glab resolves `--hostname` through these three keys, so a host that sends the call over
        # http, to another address or without certificate checks is not one this read may name.
        if (
            (key == "api_protocol" and value != "https")
            or (key == "api_host" and value != current)
            or (key == "skip_tls_verify" and value in {"true", "yes", "on", "1"})
        ):
            redirected.add(current)
    return frozenset(hosts - redirected)


_SIGNED_OUT = re.compile(
    r"gh auth login|not logged in|authentication required|bad credentials", re.IGNORECASE
)
_NOT_FOUND = re.compile(
    r"could not resolve to a pull\s?request|no pull requests? found|not found", re.IGNORECASE
)
_RATE = re.compile(r"rate limit", re.IGNORECASE)
_GL_SIGNED_OUT = re.compile(
    r"\b401\b|unauthori[sz]ed|glab auth login|not (?:logged in|authenticated)|invalid token",
    re.IGNORECASE,
)
_GL_NOT_FOUND = re.compile(r"\b40[34]\b|not found|forbidden", re.IGNORECASE)
_GL_RATE = re.compile(r"\b429\b|rate limit|too many requests", re.IGNORECASE)
_NO_CHECKS = re.compile(r"no (?:required )?checks reported", re.IGNORECASE)


def _error_token(stderr: str, *, glab: bool = False) -> str:
    """The one closed token a CLI failure becomes. The text it came from is dropped here."""
    for pattern, token in (
        (
            _GL_SIGNED_OUT if glab else _SIGNED_OUT,
            ERROR_GLAB_SIGNED_OUT if glab else ERROR_SIGNED_OUT,
        ),
        (_GL_RATE if glab else _RATE, ERROR_RATE_LIMITED),
        (_GL_NOT_FOUND if glab else _NOT_FOUND, ERROR_NOT_FOUND),
    ):
        if pattern.search(stderr):
            return token
    return ERROR_GLAB_FAILED if glab else ERROR_FAILED


class _FailureError(Exception):
    def __init__(self, token: str) -> None:
        super().__init__(token)
        self.token = token


def _run(
    runner: Callable[..., Any],
    binary: str,
    argv: Sequence[str],
    environ: Mapping[str, str],
    *,
    glab: bool = False,
) -> Any:
    """One `gh` call: its JSON whatever the exit code, or a `_FailureError` with a closed token.

    A `glab api` call is the other way round: it exits non-zero only when the server refused, and
    the body it then prints is the refusal, so a non-zero exit is classified and never read.
    """
    failed = ERROR_GLAB_FAILED if glab else ERROR_FAILED
    with (
        tempfile.TemporaryDirectory(prefix="compass-ci-cwd-") as cwd,
        tempfile.TemporaryDirectory(prefix="compass-ci-out-") as out_dir,
    ):
        out_path = os.path.join(out_dir, "stdout")
        err_path = os.path.join(out_dir, "stderr")
        options: dict[str, Any] = {}
        if runner is supervise.run:
            options["output_limits"] = (
                (out_path, OUTPUT_LIMIT_BYTES),
                (err_path, STDERR_LIMIT_BYTES),
            )
        try:
            with open(out_path, "wb") as out, open(err_path, "wb") as err:
                result = runner(
                    [binary, *argv],
                    # Closed rather than inherited: a prompt reads nothing and is never waited on.
                    input=b"",
                    cwd=cwd,
                    stdout=out,
                    stderr=err,
                    env=environ,
                    timeout=TIMEOUT_SEC,
                    check=False,
                    **options,
                )
        except subprocess.TimeoutExpired:
            raise _FailureError(ERROR_TIMEOUT) from None
        except supervise.OversizedError:
            raise _FailureError(ERROR_OUTPUT) from None
        except (OSError, subprocess.SubprocessError):
            raise _FailureError(failed) from None
        stdout = runtime_io.read_prefix_bytes(out_path, max_bytes=OUTPUT_LIMIT_BYTES + 1)
        stderr = runtime_io.read_prefix_bytes(err_path, max_bytes=STDERR_LIMIT_BYTES)
    if len(stdout) > OUTPUT_LIMIT_BYTES:
        raise _FailureError(ERROR_OUTPUT)
    text = stderr.decode("utf-8", "replace")
    exit_code = getattr(result, "returncode", 1)
    if glab and exit_code:
        # The refusal's own message is classified here and dropped, as stderr is.
        raise _FailureError(
            _error_token(f"{text} {stdout[:4096].decode('utf-8', 'replace')}", glab=True)
        )
    try:
        return json.loads(stdout)
    except (ValueError, RecursionError):
        pass
    if not stdout.strip() and _NO_CHECKS.search(text):
        return []
    if stdout.strip():
        raise _FailureError(ERROR_OUTPUT)
    raise _FailureError(_error_token(text, glab=glab) if exit_code else ERROR_OUTPUT)


def clean_name(value: Any) -> str:
    """A check name in the closed character set, clipped. Never empty."""
    text = _NAME_CHARS.sub("_", " ".join(str(value or "").split()))[:NAME_CAP_CHARS].strip()
    return text or "check"


def _epoch(value: Any) -> float | None:
    """A completion time, or None. GitHub writes `0001-01-01T00:00:00Z` for one not yet complete."""
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
        stamp = parsed.timestamp()
    except (ValueError, OverflowError, OSError):
        return None
    return stamp if stamp > 0 else None


def _parse_checks(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list) or len(value) > MAX_COUNTED:
        raise _FailureError(ERROR_OUTPUT)
    rows: list[dict[str, Any]] = []
    for item in value:
        bucket = item.get("bucket") if isinstance(item, dict) else None
        if bucket not in BUCKETS:
            raise _FailureError(ERROR_OUTPUT)
        rows.append(
            {
                "name": clean_name(item.get("name")),
                "bucket": bucket,
                "completed_at": _epoch(item.get("completedAt")),
            }
        )
    return rows


def _head(value: Any) -> tuple[str, int]:
    """The head commit and number a `gh pr view --json headRefOid,number` answer holds."""
    head = value.get("headRefOid") if isinstance(value, dict) else None
    number = value.get("number") if isinstance(value, dict) else None
    if (
        not isinstance(head, str)
        or _HEAD_RE.fullmatch(head) is None
        or type(number) is not int
        or not 0 < number <= _NUMBER_MAX
    ):
        raise _FailureError(ERROR_OUTPUT)
    return head, number


def _counts(rows: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    counts = dict.fromkeys(BUCKETS, 0)
    for row in rows:
        counts[row["bucket"]] += 1
    return counts


_LISTING_ORDER = {BUCKET_FAIL: 0, BUCKET_PENDING: 1, BUCKET_CANCEL: 2, BUCKET_PASS: 3}


def _listed(rows: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(rows, key=lambda row: _LISTING_ORDER.get(row["bucket"], 4))[:MAX_LISTED]


class Floor:
    """The cache floor: a pull request read within `FLOOR_SEC` of the last one is not read again.

    One read per pull request per press is the ruling, and a reader who presses twice in a row
    (or two sessions on one pull request) has no new fact to ask GitHub for. Only a read that
    answered is kept: a missing or signed-out `gh` is the very thing a reader fixes and presses
    again, and would otherwise be told the old answer for half a minute.
    """

    FLOOR_SEC = 30.0
    MAX_KEPT = 64

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._kept: dict[tuple[Any, ...], tuple[float, dict[str, Any]]] = {}

    def get(self, key: tuple[Any, ...], now: float) -> dict[str, Any] | None:
        with self._lock:
            kept = self._kept.get(key)
        if kept is None or not 0 <= now - kept[0] < self.FLOOR_SEC:
            return None
        copy: dict[str, Any] = json.loads(json.dumps(kept[1]))
        return copy

    def put(self, key: tuple[Any, ...], now: float, record: dict[str, Any]) -> None:
        with self._lock:
            if len(self._kept) >= self.MAX_KEPT:
                self._kept.pop(next(iter(self._kept)))
            self._kept[key] = (now, json.loads(json.dumps(record)))

    def clear(self) -> None:
        with self._lock:
            self._kept.clear()


FLOOR: Final = Floor()


def read(
    binding: Binding,
    *,
    session_head: str,
    caution: bool,
    now: float,
    environ: Mapping[str, str] | None = None,
    runner: Callable[..., Any] = supervise.run,
    floor: Floor | None = None,
) -> dict[str, Any]:
    """One press's read of one pull request: the stored record, with `error` set when it failed.

    Validated before any subprocess: a repository, number or branch that is not a plain name
    launches nothing. The head commit is read before the checks and again after them, and a
    head that moved between the two matches nothing.
    """

    key = (binding.repository, binding.number, binding.branch, session_head, caution)
    if floor is not None and (kept := floor.get(key, now)) is not None:
        return kept
    record = _read_once(binding, session_head, caution, now, environ, runner)
    if floor is not None and not record["error"]:
        floor.put(key, now, record)
    return record


def _read_once(
    binding: Binding,
    session_head: str,
    caution: bool,
    now: float,
    environ: Mapping[str, str] | None,
    runner: Callable[..., Any],
) -> dict[str, Any]:
    """One uncached read: `read` without the floor."""
    record: dict[str, Any] = {
        "read_at": now,
        "error": "",
        "source": binding.source,
        "repository": binding.repository,
        "number": binding.number,
        "head": "",
        "session_head": session_head if _HEAD_RE.fullmatch(session_head) else "",
        "head_matches": False,
        "required_only": False,
        "counts": dict.fromkeys(BUCKETS, 0),
        "caution": caution,
        "checks": [],
    }
    if not valid_repository(binding.repository) or not (
        0 < binding.number <= _NUMBER_MAX
        or (binding.number == 0 and _usable_branch(binding.branch))
    ):
        return {**record, "error": ERROR_FAILED}
    if host_of(binding.repository) != HOST:
        return _read_gitlab(binding, record, environ, runner)
    env = environment(os.environ if environ is None else environ)
    binary = git_status.executable("gh", env)
    if binary is None:
        return {**record, "error": ERROR_MISSING}
    where = ["--repo", f"{HOST}/{binding.repository}"]
    viewing = [
        "pr",
        "view",
        binding.branch or str(binding.number),
        *where,
        "--json",
        "headRefOid,number",
    ]
    try:
        head, number = _head(_run(runner, binary, viewing, env))
        listing = [
            "pr",
            "checks",
            str(number),
            *where,
            "--json",
            "name,state,bucket,completedAt",
        ]
        rows = _parse_checks(_run(runner, binary, listing, env))
        required = frozenset(
            row["name"]
            for row in _parse_checks(_run(runner, binary, [*listing, "--required"], env))
        )
        # The head again, by the number now: `gh pr checks` names no commit, so a push between the
        # first look and the listing would put the new commit's checks under the old head. A head
        # that moved is the one reported, and it matches nothing.
        later, _ = _head(_run(runner, binary, [*viewing[:2], str(number), *viewing[3:]], env))
    except _FailureError as failure:
        return {**record, "error": failure.token}
    moved = later != head
    head = later
    # Where GitHub names required checks they are the ones that count and the ones listed, and
    # the counts are over that same set, so the page's sentence and the verdict read one thing.
    if required:
        rows = [row for row in rows if row["name"] in required]
    return {
        **record,
        "number": number,
        "head": head,
        "head_matches": not moved
        and bool(record["session_head"])
        and head == record["session_head"],
        "required_only": bool(required),
        "counts": _counts(rows),
        "checks": _listed(rows),
    }


_PIPELINE_PAGE: Final = 100
_PIPELINE_PAGES: Final = 10


def _gitlab_bucket(status: Any, *, allow_failure: bool = False) -> str:
    """The bucket a GitLab status becomes, from a closed table. Anything else is unreadable.

    A job allowed to fail that failed does not fail the pipeline, and a manual job nobody ran
    blocks it only when it may not be skipped, so the first counts as neither and the second as
    pending. Treating either as a failure or a pass would say what GitLab does not.
    """
    if status == "manual":
        return BUCKET_SKIPPING if allow_failure else BUCKET_PENDING
    bucket = _GITLAB_STATUS_BUCKET.get(status) if isinstance(status, str) else None
    if bucket is None:
        raise _FailureError(ERROR_OUTPUT)
    return BUCKET_SKIPPING if bucket == BUCKET_FAIL and allow_failure else bucket


def _merge_request(value: Any, number: int) -> tuple[str, int, str, str]:
    """`(head, pipeline id, status, pipeline sha)` of a merge request answer; id 0 when none."""
    head = value.get("sha") if isinstance(value, dict) else None
    if (
        not isinstance(head, str)
        or _HEAD_RE.fullmatch(head) is None
        or value.get("iid") != number
        or type(value.get("iid")) is not int
    ):
        raise _FailureError(ERROR_OUTPUT)
    pipeline = value.get("head_pipeline")
    if pipeline is None:
        return head, 0, "", ""
    identifier = pipeline.get("id") if isinstance(pipeline, dict) else None
    status = pipeline.get("status") if isinstance(pipeline, dict) else None
    ran = pipeline.get("sha") if isinstance(pipeline, dict) else None
    if (
        type(identifier) is not int
        or not 0 < identifier <= 2**53
        or not isinstance(status, str)
        or not isinstance(ran, str)
        or _HEAD_RE.fullmatch(ran) is None
    ):
        raise _FailureError(ERROR_OUTPUT)
    _gitlab_bucket(status)
    return head, identifier, status, ran


def _parse_jobs(pages: Sequence[Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for page in pages:
        if not isinstance(page, list):
            raise _FailureError(ERROR_OUTPUT)
        for item in page:
            if not isinstance(item, dict) or not isinstance(item.get("name"), str):
                raise _FailureError(ERROR_OUTPUT)
            allowed = item.get("allow_failure", False)
            if type(allowed) is not bool:
                raise _FailureError(ERROR_OUTPUT)
            rows.append(
                {
                    "name": clean_name(item["name"]),
                    "bucket": _gitlab_bucket(item.get("status"), allow_failure=allowed),
                    "completed_at": _epoch(item.get("finished_at")),
                }
            )
    if len(rows) > MAX_COUNTED:
        raise _FailureError(ERROR_OUTPUT)
    return rows


def _job_pages(call: Callable[[str], Any], project: str, pipeline: int) -> list[Any]:
    pages: list[Any] = []
    for index in range(1, _PIPELINE_PAGES + 1):
        page = call(f"{project}/pipelines/{pipeline}/jobs?per_page={_PIPELINE_PAGE}&page={index}")
        pages.append(page)
        if not isinstance(page, list) or len(page) < _PIPELINE_PAGE:
            return pages
    # Ten full pages is more jobs than a reading can use, and listing some of them could let a
    # pass stand over a failure that was not listed.
    raise _FailureError(ERROR_OUTPUT)


def _read_gitlab(
    binding: Binding,
    record: dict[str, Any],
    environ: Mapping[str, str] | None,
    runner: Callable[..., Any],
) -> dict[str, Any]:
    """One merge request's pipeline, through `glab api` on a host glab's own configuration names.

    The hosts file is read before anything is launched, so a goal that names another host starts
    no process at all. Every call is a fixed GET of the merge request or of its pipeline's jobs;
    the project path is percent-encoded from a validated name and the numbers are integers.
    """
    source = os.environ if environ is None else environ
    host, _, path = binding.repository.partition("/")
    if host not in glab_hosts(source):
        return {**record, "error": ERROR_HOST}
    env = glab_environment(source)
    binary = git_status.executable("glab", env)
    if binary is None:
        return {**record, "error": ERROR_GLAB_MISSING}
    project = f"projects/{quote(path, safe='')}"

    def call(endpoint: str) -> Any:
        argv = ["api", endpoint, "--hostname", host, "--method", "GET"]
        return _run(runner, binary, argv, env, glab=True)

    merge_request = f"{project}/merge_requests/{binding.number}"
    try:
        head, pipeline, status, ran = _merge_request(call(merge_request), binding.number)
        rows: list[dict[str, Any]] = []
        if pipeline:
            pages = _job_pages(call, project, pipeline)
            rows = _parse_jobs(pages)
            # A trigger job whose child pipeline failed is no job of this pipeline, so a pipeline
            # that disagrees with its own jobs is named as a check of its own.
            overall = _gitlab_bucket(status)
            if overall in (BUCKET_FAIL, BUCKET_PENDING, BUCKET_CANCEL) and not any(
                row["bucket"] == overall for row in rows
            ):
                rows.append({"name": "pipeline", "bucket": overall, "completed_at": None})
        later, later_pipeline, _, later_ran = _merge_request(call(merge_request), binding.number)
    except _FailureError as failure:
        return {**record, "error": failure.token}
    moved = later != head or later_pipeline != pipeline or later_ran != ran
    # The pipeline must have run the request's head itself. A merged-results pipeline runs a merge
    # commit, so it fails safe to "not this session's commit".
    ran_head = not pipeline or later_ran == later
    return {
        **record,
        "head": later,
        "head_matches": not moved
        and ran_head
        and bool(record["session_head"])
        and later == record["session_head"],
        "counts": _counts(rows),
        "checks": _listed(rows),
    }


# --- the stored shape ---------------------------------------------------------------------------

RECORD_KEYS: Final = (
    "read_at",
    "error",
    "source",
    "repository",
    "number",
    "head",
    "session_head",
    "head_matches",
    "required_only",
    "counts",
    "caution",
    "checks",
)
_CHECK_KEYS = ("name", "bucket", "completed_at")


def _count(value: Any) -> bool:
    return type(value) is int and 0 <= value <= MAX_COUNTED


def _stamp(value: Any) -> bool:
    return (
        not isinstance(value, bool)
        and isinstance(value, (int, float))
        and 0 < value <= 253402300799
    )


def validate(value: Any) -> dict[str, Any] | None:
    """A stored record exactly as `read` writes one, or None. Nothing is repaired.

    Closed tokens and plain values only: the page maps each token to a sentence it owns, so a
    sidecar rewritten to say something else refuses the reading whole.
    """
    if not isinstance(value, dict) or set(value) != set(RECORD_KEYS):
        return None
    counts, checks = value["counts"], value["checks"]
    if (
        not _stamp(value["read_at"])
        or value["error"] not in ("", *ERRORS)
        or value["source"] not in SOURCES
        or not isinstance(value["repository"], str)
        or not valid_repository(value["repository"])
        or type(value["number"]) is not int
        or not 0 <= value["number"] <= _NUMBER_MAX
        or any(
            not isinstance(value[key], str)
            or (value[key] != "" and not _HEAD_RE.fullmatch(value[key]))
            for key in ("head", "session_head")
        )
        or any(type(value[key]) is not bool for key in ("head_matches", "required_only", "caution"))
        or not isinstance(counts, dict)
        or set(counts) != set(BUCKETS)
        or not all(_count(counts[bucket]) for bucket in BUCKETS)
        or not isinstance(checks, list)
        or len(checks) > MAX_LISTED
        or (value["head_matches"] and (not value["head"] or value["head"] != value["session_head"]))
        or (value["error"] == "" and value["number"] == 0)
    ):
        return None
    clean: list[dict[str, Any]] = []
    for item in checks:
        if (
            not isinstance(item, dict)
            or set(item) != set(_CHECK_KEYS)
            or item["bucket"] not in BUCKETS
            or not isinstance(item["name"], str)
            or clean_name(item["name"]) != item["name"]
            or not (item["completed_at"] is None or _stamp(item["completed_at"]))
        ):
            return None
        clean.append(
            {
                "name": item["name"],
                "bucket": item["bucket"],
                "completed_at": None
                if item["completed_at"] is None
                else float(item["completed_at"]),
            }
        )
    return {**value, "read_at": float(value["read_at"]), "counts": dict(counts), "checks": clean}


# --- the facts ----------------------------------------------------------------------------------

_WORDS = {
    BUCKET_PASS: "passed on the pull request",
    BUCKET_FAIL: "failed on the pull request",
    BUCKET_PENDING: "still running on the pull request",
    BUCKET_SKIPPING: "skipped on the pull request",
    BUCKET_CANCEL: "cancelled on the pull request",
}
_RESULT = {
    BUCKET_PASS: "passed",
    BUCKET_FAIL: "failed",
    BUCKET_PENDING: "pending",
    BUCKET_SKIPPING: "skipped",
    BUCKET_CANCEL: "cancelled",
}
SOURCE_TEXT: Final = "GitHub pull request check, read by Compass"
SOURCE_TEXT_GITLAB: Final = "GitLab merge request pipeline job, read by Compass"
HEAD_MOVED_TEXT: Final = "the pull request head is not this session's commit"
CAUTION_TEXT: Final = "this session changed the CI configuration"


def green(record: Mapping[str, Any]) -> bool:
    """Whether the checks that count are all in and none failed.

    Pending is never a pass, and a cancelled check is neither a pass nor ignorable. A skipped
    check counts as neither, so a pass among the ones that ran stands, and no completed check at
    all is no result. The counts are over every check that counts, not only the listed ones.
    """
    counts = record["counts"]
    return bool(
        counts[BUCKET_PASS]
        and not counts[BUCKET_FAIL]
        and not counts[BUCKET_PENDING]
        and not counts[BUCKET_CANCEL]
    )


def facts(record: Mapping[str, Any] | None, harness: str, sid: str) -> list[dict[str, Any]]:
    """One `ci_check` fact per listed check, built from a stored record, or none.

    A pass counts (`ci_counts`) only when the whole considered set is green and the pull request's
    head is the session folder's HEAD; a failure counts when that head is. Anything else is listed
    so the reading can say it, and settles nothing. The fact's time is the read's, because what
    the pull request showed is a state at the press and not an event in the session.
    """
    if not isinstance(record, dict) or record.get("error") or not record.get("checks"):
        return []
    at = float(record["read_at"])
    gitlab = host_of(record["repository"]) != HOST
    whole = green(record)
    out: list[dict[str, Any]] = []
    for index, row in enumerate(record["checks"]):
        bucket = row["bucket"]
        counted = record["head_matches"] and (
            (bucket == BUCKET_PASS and whole) or bucket == BUCKET_FAIL
        )
        notes = [
            note
            for note, holds in (
                (HEAD_MOVED_TEXT, not record["head_matches"]),
                (CAUTION_TEXT, record["caution"]),
            )
            if holds
        ]
        summary = f"{json.dumps(row['name'])} {_WORDS[bucket]}" + (
            f"; {'; '.join(notes)}" if notes else ""
        )
        out.append(
            {
                "fact_id": f"ci:{record['number']}:{index}",
                "type": FACT_TYPE,
                "subject": FACT_SUBJECT,
                "by": "gitlab" if gitlab else "github",
                "summary": summary,
                "at": at,
                "result": _RESULT[bucket],
                "ci_counts": bool(counted),
                "completed_at": row["completed_at"],
                "ci_repository": record["repository"],
                "ci_number": record["number"],
                "source_session": {"harness": harness, "sid": sid},
                "evidence": {
                    "source": SOURCE_TEXT_GITLAB if gitlab else SOURCE_TEXT,
                    "confidence": "recorded",
                },
            }
        )
    return out


def probe_session(
    config: RuntimeConfig,
    folder: str,
    runner: Callable[..., Any] = subprocess.run,
) -> git_status.GitIdentity | None:
    """The folder's commit and `origin`, or None when the git probe is off or reads nothing."""
    if not config.git_probe_enabled or not folder:
        return None
    return git_status.identity(folder, timeout_sec=config.git_probe_timeout_sec, runner=runner)


def folder_remote(
    config: RuntimeConfig, folder: str, held: git_status.StampCache | None = None
) -> tuple[str, str]:
    """The folder's `origin` as a host and repository, two empty strings where nothing is read.

    With `held` (the runtime's, so every collect and live replay of a session that polled CI
    shares one reading) a folder whose `HEAD` and `config` stats have not moved starts no git
    process. A folder with no stamp, and one whose probe read nothing, is read afresh each time.
    """
    stamp = git_status.remote_stamp(folder) if held is not None and folder else None
    if held is not None and stamp is not None:
        kept = held.get(folder, stamp)
        if kept is not None:
            return kept
    found = probe_session(config, folder)
    remote = (found.host, found.repository) if found else ("", "")
    if held is not None and stamp is not None and found is not None:
        held.put(folder, stamp, remote)
    return remote
