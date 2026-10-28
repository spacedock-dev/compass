"""Who reads a session, and the words a reader sees before pressing.

One resolver for the page, the reading route and the stamp, so the provider a
reader was told about is the provider that runs. It is pure except for
`shutil.which`: it never starts a model, and it reads each provider's gate
before looking for its CLI, so a gated provider is never even looked up.

A route depends only on the session's harness and on this machine, never on
the session, which is why the reading route can resolve one from the payload's
harness without confirming that a session exists.
See [DEC-21](docs/design-reading-a-session.md#amended-2026-09-23-claude-code-is-built-and-gated).
"""

from __future__ import annotations

import ipaddress
import json
import os
import platform
import re
import shutil
from pathlib import Path
from typing import TYPE_CHECKING, Any, TypedDict
from urllib.parse import urlsplit

from . import annotations as annotation_store
from . import ci_read, observer, records
from . import config as runtime_config

if TYPE_CHECKING:
    from collections.abc import Callable, Collection, Iterable, Mapping

CODEX = "codex"
CLAUDE = "claude"
PROVIDERS = (CODEX, CLAUDE)
LABELS = {CODEX: "Codex", CLAUDE: "Claude Code"}
VENDORS = {CODEX: "OpenAI", CLAUDE: "Anthropic"}
BINARIES = {CODEX: "codex", CLAUDE: "claude"}
MODELS = {CODEX: observer.OBSERVER_MODEL, CLAUDE: observer.CLAUDE_READING_MODEL}
# Which session harness is each provider's own. Every other harness has no
# producer of its own and prefers Codex, the producer that existed first.
OWN_HARNESS = {CODEX: "codex", CLAUDE: "claude"}

# Why this provider, or why none, as a closed token set. Four "none" tokens
# rather than one, because "not installed" and "not yet qualified" ask a
# reader to do different things and the ruling makes the second its own state.
REASON_OWN_HARNESS = "own-harness"
REASON_NO_OWN_PRODUCER = "no-own-producer"
REASON_FALLBACK_MISSING = "fallback-not-installed"
REASON_FALLBACK_UNQUALIFIED = "fallback-not-qualified"
REASON_NOT_INSTALLED = "not-installed"
REASON_MISSING_OTHER_UNQUALIFIED = "not-installed-other-not-qualified"
REASON_UNQUALIFIED_OTHER_MISSING = "not-qualified-other-not-installed"
REASON_UNQUALIFIED = "not-qualified"
REASONS = (
    REASON_OWN_HARNESS,
    REASON_NO_OWN_PRODUCER,
    REASON_FALLBACK_MISSING,
    REASON_FALLBACK_UNQUALIFIED,
    REASON_NOT_INSTALLED,
    REASON_MISSING_OTHER_UNQUALIFIED,
    REASON_UNQUALIFIED_OTHER_MISSING,
    REASON_UNQUALIFIED,
)
_NONE_REASONS = {
    ("missing", "missing"): REASON_NOT_INSTALLED,
    ("missing", "unqualified"): REASON_MISSING_OTHER_UNQUALIFIED,
    ("unqualified", "missing"): REASON_UNQUALIFIED_OTHER_MISSING,
    ("unqualified", "unqualified"): REASON_UNQUALIFIED,
}

_UNQUALIFIED = {
    CLAUDE: "Claude Code checks are not qualified on this build",
    CODEX: "Codex checks are not qualified on this build",
}
_NO_PRODUCER = "This harness has no reading producer of its own"


class Route(TypedDict):
    harness: str
    provider: str
    label: str
    vendor: str
    model: str
    reason: str
    note: str
    disclosure: str
    # The disclosure as the list items it is built from, in order, each
    # unreworded: `" ".join(disclosure_parts) == disclosure`, which a test
    # holds. The consent step and the "What is sent" popover both draw this
    # list, so the two cannot diverge; empty where there is no disclosure.
    disclosure_parts: list[str]
    fallback: bool
    # Where tool output would reach as configured on this machine, or "" where
    # the build cannot name it, and the sentence saying so. Both are empty
    # destinations-wise on a harness whose record lists no checks.
    destination: str
    tool_output: str
    # Where the reader's words go on this route, on every harness, as
    # `destination` (the function) names it, or "" where it cannot. The Allow
    # for the words is bound to it (owner, 2026-10-02): a press carries it, and
    # the policy covers the press only while it is unchanged.
    words_destination: str
    # Whether a press on this route reads the bound pull request's CI checks from GitHub:
    # `on`, `off` (the page's setting) or `flag-off` (`--no-ci-read`). The unasked lane is
    # never `on`, because no network call happens without a press.
    ci_read: str


# The harness whose observed record lists checks (`project_context.
# claude_tool_reports`). A route for any other harness has no tool output to
# send, so it names none.
TOOL_OUTPUT_HARNESSES = ("claude",)
# How much of a check's output a reading carries: the ledger cap the record
# already reads it under, item 5 of the ruling `reading.build_ledger` cites.
TOOL_OUTPUT_TAIL_CHARS = 180

# Where each CLI reads settings that still apply under the flags a reading
# passes (`--restricted` for Claude Code, `--ignore-user-config` for Codex).
# Measured in the live binaries on 2026-09-24, Claude Code 2.1.281 and
# codex-cli 0.156.1, rather than recalled: the Windows path is under Program
# Files, not ProgramData. Windows policy lives in the registry as well, which
# this build does not read, so no destination is named on Windows at all.
CLAUDE_MANAGED_DIRS = {
    "Darwin": "/Library/Application Support/ClaudeCode",
    "Linux": "/etc/claude-code",
}
CLAUDE_MANAGED_PREFERENCES = "com.anthropic.claudecode.plist"
CODEX_MANAGED_FILES = ("/etc/codex/managed_config.toml", "/etc/codex/config.toml")
CODEX_MANAGED_PREFERENCES = "com.openai.codex.plist"
MANAGED_PREFERENCES_DIR = "/Library/Managed Preferences"
_TRUE = frozenset({"1", "true", "yes", "on"})
_FALSE = frozenset({"", "0", "false", "no", "off"})
_CLAUDE_CLOUDS = {
    "CLAUDE_CODE_USE_BEDROCK": "Amazon Bedrock",
    "CLAUDE_CODE_USE_VERTEX": "Google Vertex AI",
}


class _UnnamedError(Exception):
    """A setting exists that this build cannot read or does not recognise."""


def _under(root: Path, path: str) -> Path:
    return root / path.lstrip("/")


def _present(path: Path) -> bool:
    try:
        os.lstat(path)
    except FileNotFoundError:
        return False
    except OSError as exc:
        raise _UnnamedError from exc
    return True


def _env_block(path: Path) -> dict[str, str]:
    """A settings file's `env` block, {} when absent, refused when unreadable."""
    if not _present(path):
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, RecursionError) as exc:
        raise _UnnamedError from exc
    if not isinstance(data, dict):
        raise _UnnamedError
    env = data.get("env", {})
    if not isinstance(env, dict) or not all(
        isinstance(key, str) and isinstance(value, str) for key, value in env.items()
    ):
        raise _UnnamedError
    return env


def _account(environ: Mapping[str, str]) -> tuple[str, str]:
    """(home, user) as the CLI finds them: the environment, else the password file.

    Node's `os.homedir()` and `os.userInfo()` fall back to the password entry,
    so a daemon started without `HOME` or `USER` still has a remote settings
    file and a per-user profile the CLI reads (review, 2026-09-24).
    """
    home, user = environ.get("HOME", ""), environ.get("USER", "")
    if home and user:
        return home, user
    try:
        import pwd  # noqa: PLC0415 - absent on Windows, which names nothing anyway

        entry = pwd.getpwuid(os.getuid())
    except (ImportError, KeyError, OSError):
        return home, user
    return home or entry.pw_dir, user or entry.pw_name


def _claude_sources(environ: Mapping[str, str], root: Path, system: str) -> list[Mapping[str, str]]:
    managed = CLAUDE_MANAGED_DIRS.get(system)
    if managed is None or environ.get("CLAUDE_CODE_MANAGED_SETTINGS_PATH"):
        raise _UnnamedError
    base = _under(root, managed)
    sources: list[Mapping[str, str]] = [environ, _env_block(base / "managed-settings.json")]
    drop_ins = base / "managed-settings.d"
    if _present(drop_ins):
        try:
            names = sorted(
                name
                for name in os.listdir(drop_ins)
                if name.endswith(".json") and not name.startswith(".")
            )
        except OSError as exc:
            raise _UnnamedError from exc
        sources.extend(_env_block(drop_ins / name) for name in names)
    home, user = _account(environ)
    if not home or not user:
        # Where the CLI would look cannot be known, so what it reads cannot be.
        raise _UnnamedError
    if system == "Darwin" and any(
        _present(_under(root, f"{MANAGED_PREFERENCES_DIR}/{prefix}{CLAUDE_MANAGED_PREFERENCES}"))
        for prefix in ("", f"{user}/")
    ):
        raise _UnnamedError
    config_dir = environ.get("CLAUDE_CONFIG_DIR") or f"{home}/.claude"
    sources.append(_env_block(_under(root, config_dir) / "remote-settings.json"))
    return sources


# Two settings measured in the 2.1.281 binary that move the API host without a
# base URL: an approved custom OAuth host replaces the first-party base
# (FedStart), and a unix socket sends every API request to a local socket whose
# far end forwards under another machine's configuration (review, 2026-09-24).
_OAUTH_HOST = "CLAUDE_CODE_CUSTOM_OAUTH_URL"
_MOVES_HOST = (_OAUTH_HOST, "ANTHROPIC_UNIX_SOCKET")


def _endpoint_env(sources: list[Mapping[str, str]]) -> dict[str, str]:
    """The endpoint variables across every source; two that disagree name nothing."""
    merged: dict[str, str] = {}
    for source in sources:
        for key, value in source.items():
            if not key.startswith(("ANTHROPIC_", "CLAUDE_CODE_USE_", _OAUTH_HOST)):
                continue
            if key in merged and merged[key] != value:
                raise _UnnamedError
            merged[key] = value
    return merged


def _clouds(merged: Mapping[str, str]) -> list[str]:
    """The provider switches turned on; a value that is neither on nor off names nothing."""
    clouds = []
    for key, value in merged.items():
        if not key.startswith("CLAUDE_CODE_USE_"):
            continue
        flag = value.strip().lower()
        if flag not in _TRUE | _FALSE:
            raise _UnnamedError
        if flag in _TRUE:
            clouds.append(key)
    if len(clouds) > 1 or any(cloud not in _CLAUDE_CLOUDS for cloud in clouds):
        raise _UnnamedError
    return clouds


def _claude_destination(sources: list[Mapping[str, str]]) -> str:
    merged = _endpoint_env(sources)
    if any(merged.get(key, "").strip() for key in _MOVES_HOST):
        raise _UnnamedError
    clouds = _clouds(merged)
    base_urls = [
        key for key, value in merged.items() if key.endswith("_BASE_URL") and value.strip()
    ]
    if clouds:
        if base_urls:
            raise _UnnamedError
        return _CLAUDE_CLOUDS[clouds[0]]
    if not base_urls:
        return VENDORS[CLAUDE]
    if base_urls != ["ANTHROPIC_BASE_URL"]:
        raise _UnnamedError
    return _host(merged["ANTHROPIC_BASE_URL"])


# A host label as both parsers read it alike. The CLI parses a base URL with
# the WHATWG parser and this build with `urlsplit`, and the two differ on a
# backslash (WHATWG reads it as `/`), on tabs and newlines (stripped
# anywhere), on percent-escapes and non-ASCII (decoded and mapped to another
# host), and on a numeric last label (read as an IPv4 address). Measured on
# Claude Code 2.1.287 (consent F1, ui5): `http://127.0.0.1:4597\@127.0.0.1:4598`
# sent every request to 4597 where `urlsplit` reads 4598. So a URL is named only
# when nothing in it is read differently, and anything else is unnamed.
_LABEL = re.compile(r"[a-z0-9_-]+")
_NUMERIC_LABEL = re.compile(r"[0-9]+|0[xX][0-9a-fA-F]*")


def _plain_host(hostname: str, *, bracketed: bool) -> str:
    """The host as both parsers name it, or refused where they could differ."""
    if bracketed:
        try:
            return f"[{ipaddress.IPv6Address(hostname).compressed}]"
        except ValueError as exc:
            raise _UnnamedError from exc
    labels = hostname.split(".")
    if not all(_LABEL.fullmatch(label) for label in labels):
        raise _UnnamedError
    if _NUMERIC_LABEL.fullmatch(labels[-1]):
        # WHATWG reads any host ending in a number as an IPv4 address, in
        # forms `ipaddress` refuses (`127.1`, `0x7f.1`, `010.0.0.1`), so only
        # the one canonical dotted quad, which alone `ipaddress` takes, is a
        # name both give.
        try:
            ipaddress.IPv4Address(hostname)
        except ValueError as exc:
            raise _UnnamedError from exc
    return hostname


def _host(url: str) -> str:
    """Scheme-checked host and port only: never the path, query or userinfo.

    Unnamed wherever the CLI's parser could read another host from the same
    text, and wherever what would be named has a credential's shape, so a key
    can never reach the disclosure, the board or the binding as a "host".
    """
    if not url or "\\" in url or any(not "!" <= char <= "~" for char in url):
        raise _UnnamedError
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError as exc:
        raise _UnnamedError from exc
    if parts.scheme not in {"http", "https"} or not parts.hostname:
        raise _UnnamedError
    # `port` above already refused a port that is not plain digits.
    authority = parts.netloc.rpartition("@")[2]
    if records.redact_secrets(authority) != authority:
        raise _UnnamedError
    host = _plain_host(parts.hostname, bracketed=authority.startswith("["))
    return f"{host}:{port}" if port else host


def _codex_destination(environ: Mapping[str, str], root: Path, system: str) -> str:
    if system not in {"Darwin", "Linux"}:
        raise _UnnamedError
    # Whether Codex honours either variable under `--ignore-user-config` is not
    # measured, so their presence is a destination this build cannot name.
    if any(environ.get(key, "").strip() for key in ("OPENAI_BASE_URL", "OPENAI_API_BASE")):
        raise _UnnamedError
    paths = list(CODEX_MANAGED_FILES)
    if system == "Darwin":
        _home, user = _account(environ)
        if not user:
            raise _UnnamedError
        paths.append(f"{MANAGED_PREFERENCES_DIR}/{CODEX_MANAGED_PREFERENCES}")
        paths.append(f"{MANAGED_PREFERENCES_DIR}/{user}/{CODEX_MANAGED_PREFERENCES}")
    # Present at all is enough: these can move the endpoint and the build does
    # not parse them.
    if any(_present(_under(root, path)) for path in paths):
        raise _UnnamedError
    return VENDORS[CODEX]


def destination(
    provider: str,
    *,
    environ: Mapping[str, str] | None = None,
    root: Path | None = None,
    system: str | None = None,
) -> str:
    """Where this provider's reading call reaches as configured, or "".

    "" means the build cannot positively name it, and then tool output is not
    sent, item 7 of
    [DEC-23](docs/design-reading-a-session.md#dec-23-a-claude-code-sessions-record-of-its-checks-may-show-the-work).
    A proxy variable is ignored on purpose: it carries
    the call, and the vendor answering it is unchanged (owner, 2026-09-24).
    `root` and `system` exist for tests; production reads `/` on this OS.
    """
    env = os.environ if environ is None else environ
    base = Path("/") if root is None else root
    name = platform.system() if system is None else system
    try:
        if provider == CLAUDE:
            return _claude_destination(_claude_sources(env, base, name))
        if provider == CODEX:
            return _codex_destination(env, base, name)
    except _UnnamedError:
        return ""
    return ""


def destinations(
    *, environ: Mapping[str, str] | None = None, root: Path | None = None
) -> dict[str, str]:
    """Every provider's `destination` now, as the reading policy is handed it.

    The same function a route's `words_destination` comes from, so the board's
    published permission, the press check and the job agree on one value.
    """
    return {provider: destination(provider, environ=environ, root=root) for provider in PROVIDERS}


def same_vendor(provider: str, harness: str) -> bool:
    """Whether the provider reading a session is the vendor of the harness that ran it.

    A session read by its own vendor has already sent every command and its output to that
    vendor, so a reading through it exposes nothing new; another vendor has received none of it
    (the vendor rule).
    """
    return OWN_HARNESS.get(provider) == harness


# Item 2 of the vendor rule:
# [DEC-31](docs/design-reading-a-session.md#dec-31-the-text-of-a-command-that-is-not-a-check-may-leave-the-machine-by-vendor)  # noqa: E501
def tails_for(
    provider: str,
    harness: str,
    tails: Mapping[str, str],
    tier3_calls: Collection[str],
) -> dict[str, str]:
    """The output tails this provider may be sent for a session of this harness.

    Another vendor's reading gets a tier 3 command's line and exit status and no output, and a
    call that holds one sends no tail at all, since its tail is the whole call's output.
    """
    if same_vendor(provider, harness):
        return dict(tails)
    return {call: tail for call, tail in tails.items() if call not in tier3_calls}


def _tool_output_sentence(provider: str, harness: str, where: str) -> str:
    """What a check sends, or that none is sent; where it goes is the `To:` item after it.

    The expected outcome lines rode here on Claude Code while a check was the
    only evidence they were put to the model beside. Since the agent's messages
    are evidence too (owner ruling, 2026-10-03), they go with the words, and the
    `Sent:` item says so.
    """
    if not provider or harness not in TOOL_OUTPUT_HARNESSES:
        return ""
    # The agent's messages go whether or not tool output may, and an agent
    # repeats what its commands printed, so each form says so (review,
    # 2026-10-03): "not sent" must not read as "never leaves".
    if not where:
        return (
            "Tool output is not sent, because Compass cannot name where it would go, though "
            "the agent's messages may quote it."
        )
    commands = (
        "Other commands go too, with their output"
        if same_vendor(provider, harness)
        else "Other commands go with their exit status and no output"
    )
    return (
        "Tool output is included by default: a check's command, result and last "
        f"{TOOL_OUTPUT_TAIL_CHARS} characters of output as printed, the paths of the files it "
        "wrote, the repository and number of a pull request it created, and the names of skills "
        f"it used; agent messages may quote it. {commands}."
    )


# The caveat that closes every list (owner, 2026-10-02), in one item of its own.
CAVEAT = (
    "A reading is a model's account of the evidence, never a verification that the work was done."
)

# The harnesses whose record can carry work evidence, beside which the expected
# outcome lines are put to the model (`reading.WORK_EVIDENCE_BY_HARNESS`).
# Copied rather than imported, as `_WORDS_CAP` is; a test holds the two equal.
OUTCOME_HARNESSES = ("claude", "pi")
# The harnesses whose agent's own messages a reading sends, beside which the
# lines are put to the model too (`project_context.AGENT_MESSAGE_HARNESSES`,
# copied for the same reason and held equal by a test).
AGENT_MESSAGE_HARNESSES = ("claude",)


def _to_head(provider: str, where: str) -> str:
    """Where the words go, as `destination` names it (verifier ui4 C1).

    The daemon's environment decides the endpoint, so the vendor is named only
    where `destination` names it. A cloud is named as itself; a base URL by its
    host, never said to be off this machine because it may be a local gateway;
    and where nothing can be named the item says so rather than claim a vendor.
    """
    label = LABELS[provider]
    if not where:
        return f"To: wherever your {label} settings send it, which Compass cannot name"
    if where == VENDORS[provider] or where in _CLAUDE_CLOUDS.values():
        return f"To: {where}, off this machine"
    return f"To: {where}, as your {label} settings name it"


def _base_parts(
    provider: str,
    where: str | None = None,
    *,
    harness: str = "",
    tool_output: str = "",
    model: str = "",
) -> list[str]:
    """What a reading sends, to whom and through what, one short item each.

    A list since the owner's ruling of 2026-10-02, which found the paragraph
    "long and arduous to read": each item says one thing once, and nothing
    explains a mechanism a reader deciding whether to send does not need
    (verifier ui4 V2 found the first list repeating its destination, its
    redaction and its receiver's name). The `To:` item comes after everything
    it covers, tool output included, so it alone says where all of it goes and
    that it goes redacted. The Codex wording once said "Nothing leaves it"; the
    harness's own sign-in reaches its vendor, so the item names where it goes,
    never a reassurance. `where` is the route's `destination`; None means the
    vendor, for callers that only want the wording.
    """
    label = LABELS[provider]
    model_clause = f" using {model or MODELS[CLAUDE]}" if provider == CLAUDE else ""
    head = _to_head(provider, VENDORS[provider] if where is None else where)
    # On Claude Code the agent's own messages go, and the lines with them, whether or not
    # tool output may (owner ruling, 2026-10-03). On Pi a work result is sent with no
    # grant, so the lines may go with it. Elsewhere they are never sent.
    messages = "your messages"
    outcome = ""
    if harness in AGENT_MESSAGE_HARNESSES:
        messages = "your messages and the agent's messages"
        outcome = ", and your expected outcome lines"
    elif harness in OUTCOME_HARNESSES and harness not in TOOL_OUTPUT_HARNESSES:
        outcome = ", and your expected outcome lines when a work result is among them"
    cli_adds = _CLI_ADDS.get(provider, "")
    # The newest final reply goes whole (owner amendment, 2026-10-05), and it is the only
    # message that does: every other keeps the cap above, and no shell or tool output joins it.
    final = (
        "The agent's newest final reply, as its transcript records one, goes whole instead "
        f"where it fits {_FINAL_REPLY_BYTES:,} bytes."
        if harness in AGENT_MESSAGE_HARNESSES
        else ""
    )
    return [
        (
            f"Sent: your goal and a bounded set of the session's entries, with {messages} "
            f"up to {_WORDS_CAP:,} characters each{outcome}."
        ),
        *([final] if final else []),
        *([tool_output] if tool_output else []),
        (
            f"{head}, with credential shapes redacted, through your {label} CLI and its "
            f"sign-in{model_clause}, spending your capacity."
        ),
        *([cli_adds] if cli_adds else []),
    ]


def _base_disclosure(provider: str) -> str:
    """The list for `provider` with its caveat, as the one string a route joins."""
    return " ".join([*_base_parts(provider), CAVEAT])


# What the Claude Code CLI adds to every reading on its own, measured on 2.1.283
# against a local stub (DRC-4666 review, Sent F1 and F5). The owner accepted the
# account details on 2026-09-27 on condition they are said before the press.
# Its working directory is an empty temporary one; saying more than is sent is
# the safe side, so the list does not explain it (verifier ui4 V2).
_CLI_ADDS = {
    CLAUDE: (
        "That CLI also sends its working directory, platform, shell, OS version, date and "
        "device identifier, and under a Claude account sign-in your email address and "
        "account ID."
    ),
}
# The ledger's cap on a reader's own message (`reading.LEDGER_WORDS_CAP_CHARS`),
# which the `Sent:` item states. Copied rather than imported, because this module
# sits below `reading` in the import graph; a test holds the two equal.
_WORDS_CAP = 1_000
# The bytes the newest final reply may take whole: the agent's share of the prompt
# (`observer.OBSERVER_MODEL_MAX_PROMPT_BYTES` over `reading.AGENT_WORDS_SHARE_DIVISOR`). Copied
# for the same reason, and held equal by a test.
_FINAL_REPLY_BYTES = 4_096


# The one line a press's notice carries for the GitHub and GitLab read, as the ruling asks:
# [DEC-30](docs/design-reading-a-session.md#dec-30-compass-may-read-a-pull-requests-ci-state-when-the-reader-presses-analyze)  # noqa: E501
# What goes to the provider is the repository and the number, or the repository and a pushed
# branch's name where that branch is what bound the read (GitHub only); the checks that come back
# go to the model beside the rest of the entries, so the `To:` item above covers them.
CI_READ_PART = (
    "GitHub or GitLab: a request your goal or session names has checks read with your gh or glab "
    "login, sending repository and number or branch. --no-ci-read or the switch stops it."
)


def _state(provider: str, which: Callable[[str], Any]) -> str:
    # The gate first: a provider this build may not offer is never looked up.
    if not annotation_store.provider_enabled(provider):
        return "unqualified"
    binary = which(BINARIES[provider])
    return "usable" if binary and os.path.isabs(binary) else "missing"


def _clause(provider: str, state: str) -> str:
    if state == "unqualified":
        return _UNQUALIFIED[provider]
    return f"the {LABELS[provider]} CLI was not found on this machine"


def _sentence(parts: list[str], tail: str) -> str:
    text = ", and ".join(parts) + tail
    return text[:1].upper() + text[1:]


def _route(
    harness: str,
    provider: str,
    reason: str,
    note: str,
    *,
    fallback: bool,
    where: Callable[[str], str],
    claude_model: str,
    ci: str = ci_read.SETTING_OFF,
) -> Route:
    # Where the words go, on every harness; tool output, only where checks exist.
    to = where(provider) if provider else ""
    reached = to if harness in TOOL_OUTPUT_HARNESSES else ""
    sentence = _tool_output_sentence(provider, harness, reached)
    parts = (
        [
            note,
            *_base_parts(provider, to, harness=harness, tool_output=sentence, model=claude_model),
            *([CI_READ_PART] if ci == ci_read.SETTING_ON else []),
            CAVEAT,
        ]
        if provider
        else []
    )
    return {
        "harness": harness,
        "provider": provider,
        "label": LABELS.get(provider, ""),
        "vendor": VENDORS.get(provider, ""),
        "model": claude_model if provider == CLAUDE else MODELS.get(provider, ""),
        "reason": reason,
        "note": note,
        "disclosure": " ".join(parts),
        "disclosure_parts": parts,
        "fallback": fallback,
        "destination": reached,
        "tool_output": sentence,
        "words_destination": to,
        "ci_read": ci,
    }


def resolve(
    harness: str,
    *,
    binary_resolver: Callable[[str], Any] | None = None,
    environ: Mapping[str, str] | None = None,
    root: Path | None = None,
    config: runtime_config.RuntimeConfig | None = None,
    unasked: bool = False,
) -> Route:
    """The one provider that reads a session on this harness, or why none can.

    Own harness first; else the other provider, said before the press; else
    nothing. `unasked` changes only the choice on a harness with no producer
    of its own: Claude Code first there, Codex as the fallback. Never a third
    choice, and never a second provider after a launch failed: the route is
    decided once, here, before anything is spent.
    """
    which = binary_resolver or shutil.which
    claude_model = runtime_config.validate_claude_reading_model(
        config.claude_reading_model if config is not None else observer.CLAUDE_READING_MODEL
    )

    def where(provider: str) -> str:
        return destination(provider, environ=environ, root=root)

    # Never on the unasked lane: no network call happens without a press.
    ci = (
        ci_read.SETTING_OFF
        if unasked
        else ci_read.SETTING_ON
        if config is None
        else ci_read.setting(config)
    )

    # The unasked lane prefers Claude Code where no own producer exists (owner,
    # 2026-10-20); Analyze keeps Codex there, which that ruling did not change.
    preferred = (
        (CODEX if harness == OWN_HARNESS[CODEX] else CLAUDE)
        if unasked
        else (CLAUDE if harness == OWN_HARNESS[CLAUDE] else CODEX)
    )
    other = CODEX if preferred == CLAUDE else CLAUDE
    own = harness == OWN_HARNESS[preferred]
    lead = [] if own else [_NO_PRODUCER]
    first = _state(preferred, which)
    if first == "usable":
        label = LABELS[preferred]
        if own:
            return _route(
                harness,
                preferred,
                REASON_OWN_HARNESS,
                # Not "Claude Code reads this Claude Code session.": the
                # summary and the `To:` item name the CLI (verifier ui4 V2).
                "This session's own harness reads it.",
                fallback=False,
                where=where,
                claude_model=claude_model,
                ci=ci,
            )
        return _route(
            harness,
            preferred,
            REASON_NO_OWN_PRODUCER,
            f"{_NO_PRODUCER}, so {label} reads this session.",
            fallback=False,
            where=where,
            claude_model=claude_model,
            ci=ci,
        )
    second = _state(other, which)
    if second == "usable":
        return _route(
            harness,
            other,
            REASON_FALLBACK_MISSING if first == "missing" else REASON_FALLBACK_UNQUALIFIED,
            _sentence(
                [*lead, _clause(preferred, first)], f", so {LABELS[other]} reads this session."
            ),
            fallback=True,
            where=where,
            claude_model=claude_model,
            ci=ci,
        )
    # The harness's own lack stands as a sentence of its own, so the two
    # machine facts after it join with one "and" rather than a chain of them.
    lack = "".join(f"{clause}. " for clause in lead)
    return _route(
        harness,
        "",
        _NONE_REASONS[(first, second)],
        lack
        + _sentence(
            [_clause(preferred, first), _clause(other, second)],
            ", so no analysis can run for this session.",
        ),
        fallback=False,
        where=where,
        claude_model=claude_model,
        ci=ci,
    )


def resolve_all(
    harnesses: Iterable[str],
    *,
    binary_resolver: Callable[[str], Any] | None = None,
    environ: Mapping[str, str] | None = None,
    root: Path | None = None,
    config: runtime_config.RuntimeConfig | None = None,
    unasked: bool = False,
) -> dict[str, Route]:
    """One route per harness, looking each CLI up at most once per call."""
    which = binary_resolver or shutil.which
    memo: dict[str, Any] = {}

    def cached(name: str) -> Any:
        if name not in memo:
            memo[name] = which(name)
        return memo[name]

    return {
        harness: resolve(
            harness,
            binary_resolver=cached,
            environ=environ,
            root=root,
            config=config,
            unasked=unasked,
        )
        for harness in sorted(set(harnesses))
    }


def unasked_sends_failures(route: Route) -> bool:
    """Whether an unasked check on this route sends the failed results of a session's checks.

    Only Claude Code reading a Claude Code session, where the destination can be named. That
    provider runs under the owner's acceptance. A Codex fallback keeps the words-only Allow it
    runs under, which does not cover tool output.
    """
    return (
        route["provider"] == CLAUDE
        and route["harness"] in TOOL_OUTPUT_HARNESSES
        and bool(route["destination"])
    )


def unasked_parts(route: Route) -> list[str]:
    """What an unasked check sends on this route.

    The lane never sends the agent's messages or outcome lines. Where `unasked_sends_failures`
    holds it sends the failed results of a session's checks and commands as well, and a pass
    never.
    """
    provider = route["provider"]
    if not provider:
        return []
    parts = _base_parts(provider, route["words_destination"], model=route["model"])
    if unasked_sends_failures(route):
        parts.insert(
            1,
            "A check or command that failed goes too, with its masked line, its exit status and "
            f"the last {TOOL_OUTPUT_TAIL_CHARS} characters of its output as printed, except from a "
            "shell call that ran more than one thing, where only the line and exit status go. "
            "Nothing that passed is sent.",
        )
    return [*parts, CAVEAT]
