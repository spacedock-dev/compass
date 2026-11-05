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
    if not home or not user:
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
        source.remote
        or refresh
        or any(key in data for key in ("policyHelper", "forceLoginGatewayUrl"))
        or data.get("forceLoginMethod") == "gateway"
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
