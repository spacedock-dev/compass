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
    directory owned by this account and writable by nobody else, and every symbolic link on the
    way to it owned by this account or by root. The value is passed on unchanged, never
    resolved, because Claude Code names its keychain entry after the folder as written. POSIX
    only; Windows has no owner and mode bits to read, so there the folder must only exist.
    """
    if not path or not os.path.isabs(path) or os.path.normpath(path) != path.rstrip(os.sep):
        return False
    if os.name == "nt":
        return os.path.isdir(path)
    uid = os.getuid()
    walk = os.sep
    try:
        for part in [segment for segment in path.split(os.sep) if segment]:
            walk = os.path.join(walk, part)
            info = os.lstat(walk)
            if stat.S_ISLNK(info.st_mode) and info.st_uid not in {0, uid}:
                return False
        final = os.stat(path)
    except OSError:
        return False
    return (
        stat.S_ISDIR(final.st_mode)
        and final.st_uid == uid
        and not final.st_mode & (stat.S_IWGRP | stat.S_IWOTH)
    )


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
) -> list[Source]:
    """Same named managed sources destination resolution has always inspected."""
    managed = MANAGED_DIRS.get(system)
    if managed is None or environ.get("CLAUDE_CODE_MANAGED_SETTINGS_PATH"):
        raise SettingsError
    base = under(root, managed)
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
        present(under(root, f"{PREFERENCES_DIR}/{prefix}{MANAGED_PREFERENCES}"))
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


def _deployment(environments: list[Mapping[str, str]]) -> Deployment:
    cloud, gateway, unknown = False, False, False
    for env in environments:
        for key, value in env.items():
            if key.startswith("CLAUDE_CODE_USE_") and _flag(value):
                if key in {"CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_VERTEX"}:
                    cloud = True
                else:
                    unknown = True
            if key.startswith("ANTHROPIC_") and key.endswith("_BASE_URL") and value.strip():
                gateway = True
            if key in {"ANTHROPIC_UNIX_SOCKET", "CLAUDE_CODE_CUSTOM_OAUTH_URL"} and value.strip():
                unknown = True
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
_OTLP_EXPORT: Final = "OTEL_EXPORTER_OTLP_"


def exports_telemetry(env: Mapping[str, str]) -> bool:
    """Whether an environment turns on Claude Code's telemetry or names an OTLP exporter.

    Either sends what the CLI records about a call to a collector this reader cannot name. A
    switch that is neither on nor off is unreadable, as a provider switch is.
    """
    switch = env.get("CLAUDE_CODE_ENABLE_TELEMETRY")
    if switch is not None and _flag(switch):
        return True
    return any(key.startswith(_OTLP_EXPORT) and value.strip() for key, value in env.items())


def _source_flags(source: Source) -> tuple[bool, bool]:
    data = source.data
    overrides = data.get("modelOverrides", {})
    if not isinstance(overrides, dict) or not all(
        isinstance(value, str) for value in overrides.values()
    ):
        raise SettingsError
    refresh = data.get("forceRemoteSettingsRefresh", False)
    if type(refresh) is not bool:
        raise SettingsError
    dynamic = (
        (source.remote and not data.keys() <= _REMOTE_HARMLESS)
        or refresh
        or any(key in data for key in ("policyHelper", "forceLoginGatewayUrl", *SHELL_HELPERS))
        or data.get("forceLoginMethod") == "gateway"
        or exports_telemetry(data.get("env", {}))
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
        sources = documents(env, root or Path("/"), system or platform.system())
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

    The destination's half of `resolve`: a source `resolve` treats as remapped or dynamic is one
    whose receiver this reader cannot name, so the board and the refusal read one rule.
    """
    remapped, dynamic = _source_flags(source)
    return remapped or dynamic


# The refusals every Claude lane shares: an applicable source Compass cannot read, or one that
# can move the call or run a helper. The compaction and fallback conflicts are not among them,
# because they concern Analyze's own envelope (`DISABLE_COMPACT`, `switchModelsOnFlag`).
_LANE_REFUSALS: Final = frozenset({"context-config", "dynamic-policy"})


def lane_refusal(
    model: str,
    *,
    environ: Mapping[str, str] | None = None,
    root: Path | None = None,
    system: str | None = None,
) -> Refusal:
    """What a Claude lane other than Analyze refuses on before it starts the CLI, or "".

    On Windows and under WSL nothing applicable can be read, and the published destination
    already says Compass cannot name where the words go; a reading still runs on the reader's
    words there, as SECURITY.md records, so those lanes are not refused for it. Analyze keeps
    `resolve`'s whole refusal everywhere.
    """
    env = os.environ if environ is None else environ
    name = system or platform.system()
    if name not in MANAGED_DIRS or env.get("WSL_DISTRO_NAME") or env.get("WSL_INTEROP"):
        return ""
    refusal = resolve(model, environ=env, root=root, system=name).refusal
    return refusal if refusal in _LANE_REFUSALS else ""
