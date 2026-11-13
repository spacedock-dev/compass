"""Bounded applicable Claude settings and conservative Analyze controls.

Restricted mode retains managed settings. This reads their named local sources,
not user/project settings or credentials. A read is not a policy receipt: the CLI
can fetch remote policy or observe a later file mutation before/during its run.
"""

from __future__ import annotations

import json
import os
import platform
import re
import stat
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final, Literal

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

MANAGED_DIRS: Final = {
    "Darwin": "/Library/Application Support/ClaudeCode",
    "Linux": "/etc/claude-code",
}
MANAGED_PREFERENCES: Final = "com.anthropic.claudecode.plist"
PREFERENCES_DIR: Final = "/Library/Managed Preferences"
DOCUMENT_BYTES: Final = 1_048_576
DIRECTORY_ENTRIES: Final = 64
_TRUE: Final = frozenset({"1", "true", "yes", "on"})
_FALSE: Final = frozenset({"", "0", "false", "no", "off"})
_CANONICAL_MODEL: Final = re.compile(r"claude-(?:sonnet|opus|haiku)-[0-9]+(?:-[0-9]+)?")
type Deployment = Literal["direct", "gateway", "cloud", "unknown"]
type Refusal = Literal[
    "", "context-config", "dynamic-policy", "compaction-policy-conflict", "fallback-policy-conflict"
]


# Where machine-wide managed files are read under when a caller names no root: `/` in
# production. The dashboard's test support points it at an empty folder so a developer's own
# managed policy cannot decide a test; a caller that passes `root` is never redirected.
MANAGED_ROOT: Path = Path("/")


def _managed_root(root: Path | None) -> Path | None:
    return MANAGED_ROOT if root is None else None


class SettingsError(Exception):
    """An applicable source or relevant setting cannot be safely interpreted."""


def under(root: Path, path: str) -> Path:
    return root / path.lstrip("/")


def present(path: Path) -> bool:
    try:
        os.lstat(path)
    except FileNotFoundError:
        return False
    except OSError as exc:
        raise SettingsError from exc
    return True


def account(environ: Mapping[str, str]) -> tuple[str, str]:
    """Match Node's HOME/USER then password-entry fallback; no credential reads."""
    home, user = environ.get("HOME", ""), environ.get("USER", "")
    if home and user:
        return home, user
    try:
        import pwd  # noqa: PLC0415 - unavailable on Windows

        entry = pwd.getpwuid(os.getuid())
    except (ImportError, KeyError, OSError):
        return home, user
    return home or entry.pw_dir, user or entry.pw_name


def verified_folder(path: str) -> bool:
    """Whether a configuration folder named by the environment can be trusted as this account's.

    `CLAUDE_CONFIG_DIR` and `CODEX_HOME` decide where a CLI reads its sign-in and settings, so
    a folder another account could write would let that account choose both. Verified means:
    absolute and already normal (no `.` or `..` part, no doubled separator), an existing
    directory owned by this account and writable by nobody else, every symbolic link on the
    way to it owned by this account or by root, and every directory above it held the same way
    (`_held_parent`). The value is passed on unchanged, never
    resolved, because Claude Code names its keychain entry after the folder as written. POSIX
    only; Windows has no owner and mode bits to read, so there the folder must only exist.
    """
    if os.name == "nt":
        return _windows_folder(path)
    if not path or not os.path.isabs(path) or os.path.normpath(path) != path.rstrip(os.sep):
        return False
    uid = os.getuid()
    try:
        parents = _holding_folders(path, uid)
        if parents is None or not all(_held_parent(os.stat(parent), uid) for parent in parents):
            return False
        final = os.stat(path)
    except OSError:
        return False
    return (
        stat.S_ISDIR(final.st_mode)
        and final.st_uid == uid
        and not final.st_mode & stat.S_IWOTH
        and (not final.st_mode & stat.S_IWGRP or _private_group(final.st_gid, uid))
    )


# Links followed before a path counts as unverifiable: Linux's own limit, above macOS's 32.
LINK_HOPS: Final = 40


def _holding_folders(path: str, uid: int) -> set[str] | None:
    """Every real directory an entry on the way to `path` sits in, or None to refuse.

    Resolved one link at a time, as the kernel does, so a link inside a link's target adds the
    folder it sits in too: `os.path.realpath` would report only where the chain ends, and another
    account able to write a folder midway could repoint the chain later. Each link must be owned
    by this account or root, and more than `LINK_HOPS` links refuse.
    """
    pending = [part for part in path.split(os.sep) if part]
    current = os.sep
    folders: set[str] = set()
    hops = 0
    while pending:
        part = pending.pop(0)
        if part == ".":
            continue
        if part == "..":
            current = os.path.dirname(current)
            continue
        folders.add(current)
        entry = os.path.join(current, part)
        info = os.lstat(entry)
        if not stat.S_ISLNK(info.st_mode):
            current = entry
            continue
        hops += 1
        if hops > LINK_HOPS or info.st_uid not in {0, uid}:
            return None
        target = os.readlink(entry)
        if os.path.isabs(target):
            current = os.sep
        pending[:0] = [part for part in target.split(os.sep) if part]
    return folders


def _held_parent(info: os.stat_result, uid: int) -> bool:
    """Whether no other account can rename an entry out of this directory and plant its own.

    Every directory holding a part of the path, link by link (`_holding_folders`): another account
    able to write one could swap the folder, or a link to it, after the check. Owned by this
    account or root, and writable by nobody else, unless sticky (as /tmp is), where only an
    entry's owner may rename it and the entries below are checked in turn. Group write passes
    for this account's private group, as on the folder itself.
    """
    if not stat.S_ISDIR(info.st_mode) or info.st_uid not in {0, uid}:
        return False
    if info.st_mode & stat.S_ISVTX:
        return True
    if info.st_mode & stat.S_IWOTH:
        return False
    return not info.st_mode & stat.S_IWGRP or _private_group(info.st_gid, uid)


def _windows_folder(path: str) -> bool:
    """A Windows folder: a drive and a root, either separator, no `.` or `..` part, existing.

    Claude Code accepts `C:/Users/me/.claude`, which `ntpath.normpath` rewrites with backslashes,
    so the POSIX test of "already normal" would refuse a form the CLI takes. Climbing is still
    refused part by part, and a driveless root is refused because it resolves against the
    current drive.
    """
    drive, rest = os.path.splitdrive(path)
    if not drive or rest[:1] not in {"\\", "/"}:
        return False
    parts = [part for part in rest.replace("/", "\\").split("\\") if part]
    if any(part in {".", ".."} for part in parts):
        return False
    return os.path.isdir(path)


def _private_group(gid: int, uid: int) -> bool:
    """Whether `gid` is this account's own group: its primary group, named after it, no members.

    A umask of 002, the default on distributions that give every user a group of their own,
    makes a new folder group-writable; that group holds nobody else, so the write bit adds no
    writer. Any other group could hold another account. `gr_mem` lists supplementary members
    only, so the password database is read too: no other account may have this group as its
    primary one. A directory service that does not enumerate its accounts (some LDAP and SSSD
    set-ups) cannot be seen this way, and an account it alone serves goes undetected; that is
    the one case this test fails open.
    """
    import grp  # noqa: PLC0415 - POSIX only
    import pwd  # noqa: PLC0415 - POSIX only

    try:
        account = pwd.getpwuid(uid)
        group = grp.getgrgid(gid)
        if account.pw_gid != gid or group.gr_name != account.pw_name or group.gr_mem:
            return False
        # Last, because it reads every account: only once the cheap checks would admit.
        return not any(entry.pw_gid == gid and entry.pw_uid != uid for entry in pwd.getpwall())
    except (KeyError, OSError):
        return False


def _unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    data: dict[str, Any] = {}
    for key, value in pairs:
        if key in data:
            raise SettingsError
        data[key] = value
    return data


def document(path: Path) -> dict[str, Any]:
    """Missing is empty; oversized, nonregular or ambiguous documents refuse."""
    if not present(path):
        return {}
    try:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NONBLOCK", 0))
        with os.fdopen(descriptor, "rb") as source:
            if not stat.S_ISREG(os.fstat(source.fileno()).st_mode):
                raise SettingsError
            raw = source.read(DOCUMENT_BYTES + 1)
        if len(raw) > DOCUMENT_BYTES:
            raise SettingsError
        data = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique)
    except (OSError, ValueError, RecursionError) as exc:
        raise SettingsError from exc
    if not isinstance(data, dict):
        raise SettingsError
    env = data.get("env", {})
    if not isinstance(env, dict) or not all(
        isinstance(key, str) and isinstance(value, str) for key, value in env.items()
    ):
        raise SettingsError
    return data


@dataclass(frozen=True)
class Source:
    """Private source material; never publish this object or its contents."""

    data: dict[str, Any]
    remote: bool = False


def documents(
    environ: Mapping[str, str],
    root: Path,
    system: str,
    *,
    account_reader: Callable[[Mapping[str, str]], tuple[str, str]] = account,
    managed_root: Path | None = None,
) -> list[Source]:
    """Same named managed sources destination resolution has always inspected.

    `managed_root`, when given, is where the machine-wide managed files and profiles are read
    under instead of `root`; the account's own folders stay under `root`.
    """
    managed = MANAGED_DIRS.get(system)
    if managed is None or environ.get("CLAUDE_CODE_MANAGED_SETTINGS_PATH"):
        raise SettingsError
    machine = root if managed_root is None else managed_root
    base = under(machine, managed)
    sources = [Source(document(base / "managed-settings.json"))]
    drop_ins = base / "managed-settings.d"
    if present(drop_ins):
        try:
            with os.scandir(drop_ins) as entries:
                names = []
                for index, entry in enumerate(entries):
                    if index >= DIRECTORY_ENTRIES:
                        raise SettingsError
                    if entry.name.endswith(".json") and not entry.name.startswith("."):
                        names.append(entry.name)
        except OSError as exc:
            raise SettingsError from exc
        sources.extend(Source(document(drop_ins / name)) for name in sorted(names))
    home, user = account_reader(environ)
    if not home or not user or not os.path.isabs(home):
        raise SettingsError
    if environ.get("CLAUDE_CONFIG_DIR") and not verified_folder(
        str(under(root, environ["CLAUDE_CONFIG_DIR"]))
    ):
        raise SettingsError
    if system == "Darwin" and any(
        present(under(machine, f"{PREFERENCES_DIR}/{prefix}{MANAGED_PREFERENCES}"))
        for prefix in ("", f"{user}/")
    ):
        raise SettingsError
    config_dir = environ.get("CLAUDE_CONFIG_DIR") or f"{home}/.claude"
    remote = under(root, config_dir) / "remote-settings.json"
    remote_present = present(remote)
    remote_data = document(remote)
    sources.append(Source(remote_data, remote=remote_present or present(remote)))
    return sources


@dataclass(frozen=True)
class Controls:
    """Only closed labels and numeric restrictions may leave this resolver."""

    deployment: Deployment = "unknown"
    window_limits: tuple[int, ...] = ()
    refusal: Refusal = ""
    policy_verified: Literal[False] = field(default=False, init=False)


def _number(value: Any, *, environment: bool = False) -> int:
    if environment:
        if not isinstance(value, str) or not re.fullmatch(r"[0-9]{1,10}", value):
            raise SettingsError
        value = int(value)
    if type(value) is not int or not 0 < value <= 1_000_000_000:
        raise SettingsError
    return int(value)


def _flag(value: str) -> bool:
    normalized = value.strip().lower()
    if normalized not in _TRUE | _FALSE:
        raise SettingsError
    return normalized in _TRUE


def _environment_limits(env: Mapping[str, str]) -> list[int]:
    limits = []
    if "CLAUDE_CODE_DISABLE_1M_CONTEXT" in env and _flag(env["CLAUDE_CODE_DISABLE_1M_CONTEXT"]):
        limits.append(200_000)
    limits.extend(
        _number(env[key], environment=True)
        for key in ("CLAUDE_CODE_AUTO_COMPACT_WINDOW", "CLAUDE_CODE_MAX_CONTEXT_TOKENS")
        if key in env
    )
    return limits


def _document_limits(data: dict[str, Any], model: str) -> list[int]:
    limits = _environment_limits(data.get("env", {}))
    if "autoCompactWindow" in data:
        limits.append(_number(data["autoCompactWindow"]))
    models = data.get("modelSettings", {})
    if not isinstance(models, dict):
        raise SettingsError
    for name, settings in models.items():
        if not isinstance(settings, dict):
            raise SettingsError
        if "autoCompactWindow" not in settings:
            continue
        if not _CANONICAL_MODEL.fullmatch(name) and name != model:
            raise SettingsError
        value = settings["autoCompactWindow"]
        if value != "auto":
            number = _number(value)
            # A date-suffixed selected id is unknown for expanded admission,
            # but its canonical row can still impose a lower restriction.
            canonical = re.sub(r"-[0-9]{8}$", "", model)
            if name in (model, canonical):
                limits.append(number)
    return limits


def _conflict(data: dict[str, Any]) -> Refusal:
    if "switchModelsOnFlag" in data:
        if type(data["switchModelsOnFlag"]) is not bool:
            raise SettingsError
        if data["switchModelsOnFlag"]:
            return "fallback-policy-conflict"
    fallback = data.get("fallbackModel", "")
    if not isinstance(fallback, (str, list)) or (
        isinstance(fallback, list) and not all(isinstance(item, str) for item in fallback)
    ):
        raise SettingsError
    if fallback:
        return "fallback-policy-conflict"
    compact = data.get("env", {}).get("DISABLE_COMPACT")
    if compact is not None and compact != "1":
        return "compaction-policy-conflict"
    return ""


# The AWS SDK reads these to send a Bedrock call to another host than the region's own.
# Found in the 2.1.323 binary's strings (review, 2026-11-13); they move the call only while
# the Bedrock switch is on, so they mean nothing on any other route.
AWS_ENDPOINTS: Final = (
    "AWS_ENDPOINT_URL",
    "AWS_ENDPOINT_URL_BEDROCK",
    "AWS_ENDPOINT_URL_BEDROCK_RUNTIME",
)


def _deployment(environments: list[Mapping[str, str]]) -> Deployment:
    cloud, gateway, unknown, bedrock, aws_endpoint = False, False, False, False, False
    for env in environments:
        for key, value in env.items():
            if key.startswith("CLAUDE_CODE_USE_") and _flag(value):
                if key in {"CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_VERTEX"}:
                    cloud = True
                    bedrock = bedrock or key == "CLAUDE_CODE_USE_BEDROCK"
                else:
                    unknown = True
            if key in AWS_ENDPOINTS and value.strip():
                aws_endpoint = True
            if key.startswith("ANTHROPIC_") and key.endswith("_BASE_URL") and value.strip():
                gateway = True
            if key in {"ANTHROPIC_UNIX_SOCKET", "CLAUDE_CODE_CUSTOM_OAUTH_URL"} and value.strip():
                unknown = True
    unknown = unknown or (bedrock and aws_endpoint)
    return "unknown" if unknown else "gateway" if gateway else "cloud" if cloud else "direct"


# Keys a server-managed cache may hold without being able to change the model,
# model switching, the context window, compaction or fallback. An allowlist: a
# key Claude Code adds later defaults to dynamic, and `env`, `permissions` and
# `hooks` are dynamic because this reader cannot prove they cannot move the
# model. Ruling (the six keys below are the ones it names, held by a test):
# [owner ruling 2026-11-06](docs/design-reading-a-session.md#owner-ruling-2026-11-06-a-remote-settings-cache-is-dynamic-only-when-it-can-change-the-model)  # noqa: E501
_REMOTE_HARMLESS: Final = frozenset(
    {
        "$schema",
        "channelsEnabled",
        "companyAnnouncements",
        "cleanupPeriodDays",
        "includeCoAuthoredBy",
        "attribution",
    }
)


# Settings keys whose value is a command Claude Code runs through a shell before or during a
# call: to fetch a key or cloud credentials, or the headers of a telemetry export. Restricted mode
# still applies them from managed and remote settings, and Compass never names or runs one, so
# each makes the call's sign-in and destination something this reader cannot vouch for.
# https://code.claude.com/docs/en/settings-reference
SHELL_HELPERS: Final = (
    "apiKeyHelper",
    "awsAuthRefresh",
    "awsCredentialExport",
    "gcpAuthRefresh",
    "otelHeadersHelper",
)
# The switches that put a call's words into Claude Code's telemetry: the user's prompt, tool
# input and output, assistant replies and raw API bodies, read from the 2.1.323 binary's
# strings (its own help calls them content variables, OTEL_LOG_USER_PROMPTS among them). Owner
# ruling 2026-11-13: telemetry refuses and unnames only when it can carry the reading's words,
# so metrics and usage export alone (`CLAUDE_CODE_ENABLE_TELEMETRY` with an OTLP endpoint) do
# neither.
WORD_SWITCHES: Final = (
    "OTEL_LOG_USER_PROMPTS",
    "OTEL_LOG_TOOL_DETAILS",
    "OTEL_LOG_TOOL_CONTENT",
    "OTEL_LOG_ASSISTANT_RESPONSES",
    "OTEL_LOG_RAW_API_BODIES",
)


def exports_words(env: Mapping[str, str]) -> bool:
    """Whether an environment makes Claude Code's telemetry carry the call's words.

    A content switch on, or detailed beta tracing with an endpoint to send it to. A switch that
    is neither on nor off is unreadable, as a provider switch is.
    """
    if any(name in env and _flag(env[name]) for name in WORD_SWITCHES):
        return True
    detailed = env.get("ENABLE_BETA_TRACING_DETAILED")
    return (
        detailed is not None
        and _flag(detailed)
        and bool(env.get("BETA_TRACING_ENDPOINT", "").strip())
    )


def runs_hooks(source: Source) -> bool:
    """Whether a managed source names hooks that run, which can send a call's words anywhere.

    Owner ruling 2026-11-13, "Unname, don't refuse": the destination names nothing, and no lane
    refuses for it. `disableAllHooks: true` in the same source means none runs.
    """
    hooks = source.data.get("hooks")
    return bool(hooks) and source.data.get("disableAllHooks") is not True


# Keys a remote cache may hold without stopping a lane other than Analyze: hooks unname the
# destination instead (`runs_hooks`). Analyze keeps the 2026-11-06 allowlist above.
_LANE_REMOTE_HARMLESS: Final = _REMOTE_HARMLESS | {"hooks", "disableAllHooks"}


def _source_flags(source: Source, *, lane: bool = False) -> tuple[bool, bool]:
    data = source.data
    harmless = _LANE_REMOTE_HARMLESS if lane else _REMOTE_HARMLESS
    overrides = data.get("modelOverrides", {})
    if not isinstance(overrides, dict) or not all(
        isinstance(value, str) for value in overrides.values()
    ):
        raise SettingsError
    refresh = data.get("forceRemoteSettingsRefresh", False)
    if type(refresh) is not bool:
        raise SettingsError
    dynamic = (
        (source.remote and not data.keys() <= harmless)
        or refresh
        or any(key in data for key in ("policyHelper", "forceLoginGatewayUrl", *SHELL_HELPERS))
        or data.get("forceLoginMethod") == "gateway"
        or exports_words(data.get("env", {}))
    )
    # No automatic fallback is a top-level print contract, not a promise about
    # a configured named agent whose model behavior can differ.
    if "agent" in data:
        raise SettingsError
    # Managed environment can move the source lookup itself. Do not silently
    # keep reading the daemon's previous directory/profile.
    if any(
        key in data.get("env", {})
        for key in ("HOME", "USER", "CLAUDE_CONFIG_DIR", "CLAUDE_CODE_MANAGED_SETTINGS_PATH")
    ):
        raise SettingsError
    return bool(overrides), dynamic


def resolve(
    model: str,
    *,
    environ: Mapping[str, str] | None = None,
    root: Path | None = None,
    system: str | None = None,
) -> Controls:
    """Take every lower restriction, not an emulation of vendor precedence.

    Docs: settings-reference (modelSettings, policyHelper, switchModelsOnFlag),
    env-vars, and server-managed-settings (startup/background cache refresh).
    https://code.claude.com/docs/en/settings-reference
    https://code.claude.com/docs/en/server-managed-settings
    Cache absence and NONESSENTIAL_TRAFFIC never prove remote policy is absent.
    A cache holding only harmless keys is a snapshot: the organization could push
    a model-affecting setting that the CLI applies at its next launch before the
    cache shows it. The owner accepted that when ruling on 2026-11-06.
    Known applicable dynamic sources refuse; no helper or network call runs here.
    """
    env = os.environ if environ is None else environ
    # WSL can inherit Windows policy that this reader cannot inspect.
    # Destination's historical environment interpretation remains unchanged.
    if env.get("WSL_DISTRO_NAME") or env.get("WSL_INTEROP"):
        return Controls(refusal="context-config")
    if any(env.get(key) and not os.path.isabs(env[key]) for key in ("HOME", "CLAUDE_CONFIG_DIR")):
        return Controls(refusal="context-config")
    try:
        sources = documents(
            env, root or Path("/"), system or platform.system(), managed_root=_managed_root(root)
        )
        limits = _environment_limits(env)
        environments: list[Mapping[str, str]] = [env]
        dynamic, remapped = False, False
        refusal: Refusal = ""
        for source in sources:
            data = source.data
            limits.extend(_document_limits(data, model))
            environments.append(data.get("env", {}))
            refusal = refusal or _conflict(data)
            source_remapped, source_dynamic = _source_flags(source)
            remapped = remapped or source_remapped
            dynamic = dynamic or source_dynamic
        deployment: Deployment = "unknown" if remapped else _deployment(environments)
        if refusal:
            return Controls(deployment=deployment, window_limits=tuple(limits), refusal=refusal)
        return Controls(
            deployment=deployment,
            window_limits=tuple(limits),
            refusal="dynamic-policy" if dynamic else "",
        )
    except SettingsError:
        return Controls(refusal="context-config")


def unnameable(source: Source) -> bool:
    """Whether a source can move the call, its model or its sign-in where no name can follow.

    The destination's half of `resolve`: a source `resolve` treats as remapped or dynamic is
    one whose receiver this reader cannot name. The lanes refuse on the dynamic half alone
    (`lane_refusal`): a `modelOverrides` remap leaves the board naming nothing while the lanes
    still run, which is accepted, because a remap changes the model a call asks for and the
    destination already says it cannot be named.
    """
    remapped, dynamic = _source_flags(source)
    return remapped or dynamic or runs_hooks(source)


def config_folder_refused(environ: Mapping[str, str], root: Path | None = None) -> bool:
    """Whether `CLAUDE_CONFIG_DIR` is set and fails `verified_folder`, on any system."""
    value = environ.get("CLAUDE_CONFIG_DIR", "")
    if not value:
        return False
    path = value if root is None else str(under(root, value)) if os.path.isabs(value) else ""
    return not verified_folder(path)


def lane_refusal(
    model: str,
    *,
    environ: Mapping[str, str] | None = None,
    root: Path | None = None,
    system: str | None = None,
) -> Refusal:
    """What a Claude lane other than Analyze refuses on before it starts the CLI, or "".

    An unverified `CLAUDE_CONFIG_DIR` refuses everywhere, because it chooses the account the
    call signs in as. Beyond that, on Windows and under WSL nothing applicable can be read and
    the published destination already says Compass cannot name where the words go; a reading
    still runs on the reader's words there, as SECURITY.md records, so those lanes are not
    refused for it. Elsewhere the sources are read here rather than through `resolve`'s answer,
    because `resolve` names its first conflict and drops `dynamic` beside it: a helper next to a
    `fallbackModel` must still refuse. The compaction and fallback conflicts themselves concern
    Analyze's own envelope and are not lane refusals, and hooks unname the destination without
    refusing (`runs_hooks`). Analyze keeps `resolve`'s whole refusal everywhere.
    """
    env = os.environ if environ is None else environ
    if config_folder_refused(env, root):
        return "context-config"
    name = system or platform.system()
    if name not in MANAGED_DIRS or env.get("WSL_DISTRO_NAME") or env.get("WSL_INTEROP"):
        return ""
    refusal = resolve(model, environ=env, root=root, system=name).refusal
    if refusal == "context-config":
        return refusal
    try:
        sources = documents(env, root or Path("/"), name, managed_root=_managed_root(root))
        return (
            "dynamic-policy"
            if any(_source_flags(source, lane=True)[1] for source in sources)
            else ""
        )
    except SettingsError:
        return "context-config"
