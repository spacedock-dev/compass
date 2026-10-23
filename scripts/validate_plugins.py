#!/usr/bin/env python3
"""Validate the shared Codex, Claude Code, Antigravity, and Gemini contracts."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

import yaml
from yaml.constructor import ConstructorError

# Explicit shipped sources; neither a directory glob nor a runtime export can
# silently certify a newly added adapter. Host-specific probes stay separate.
JS_ADAPTERS = {"opencode_plugin.js": "opencode", "pi_extension.js": "pi"}
JS_ADAPTER_PROBE = r"""
import {createServer} from "node:http";
import {writeFileSync} from "node:fs";
import {join} from "node:path";
import {pathToFileURL} from "node:url";
const deliveries = [];
const server = createServer((req, res) => {
  let body = "";
  req.on("data", chunk => { body += chunk; });
  req.on("end", () => {
    deliveries.push({path: req.url, body: JSON.parse(body)});
    res.writeHead(204).end();
  });
});
await new Promise(resolve => server.listen(0, "127.0.0.1", resolve));
try {
  const port = server.address().port;
  process.env.COMPASS_PORT = String(port);
  writeFileSync(join(process.env.COMPASS_HOME, `compass-${port}.json`),
    JSON.stringify({capabilities: {opencode: "oracle-token", pi: "oracle-token"}}));
  const module = await import(pathToFileURL(process.argv[2]));
  const hooks = {};
  if (process.argv[3] === "pi") {
    module.default({on: (name, callback) => { hooks[name] = callback; }});
    const ctx = {sessionManager: {getSessionId: () => "12345678-1234-1234-1234-123456789abc"}};
    for (const type of ["ui_prompt_start", "ui_prompt_end"]) {
      await hooks[type]({type, reason: "ui_prompt", kind: "select"}, ctx);
      await new Promise(resolve => setTimeout(resolve, 100));
    }
  } else {
    Object.assign(hooks, await module.CompassPlugin({}));
    for (const type of ["permission.asked", "permission.replied", "session.status"]) {
      await hooks.event({event: {type, properties: {
        sessionID: "ses_" + "a".repeat(26), id: "request-one",
        requestID: "request-one", reply: "once"
      }}});
      await new Promise(resolve => setTimeout(resolve, 100));
    }
  }
  await new Promise(resolve => setTimeout(resolve, 300));
  process.stdout.write(JSON.stringify({hooks: Object.keys(hooks), deliveries}));
} finally {
  server.closeAllConnections();
  server.close();
}
"""


# One probe per distinct adapter source. The result depends only on the adapter's
# bytes and which harness it is, and each run carries about 0.5s of fixed sleeps:
# the suites asked 35 times for 10 distinct inputs, about 16s of waiting
# (measured 2026-09-23). A mutated copy has different bytes, so it is probed on
# its own; a failure raises and is never cached.
_JS_ADAPTER_RESULTS: dict[tuple[str, str], dict[str, Any]] = {}


def exercise_js_adapter(path: Path) -> dict[str, Any]:
    """Observe the actual passive callback, with no fake event-route declaration."""
    source = path.read_bytes()
    key = (path.name, hashlib.sha256(source).hexdigest())
    if key not in _JS_ADAPTER_RESULTS:
        _JS_ADAPTER_RESULTS[key] = _probe_js_adapter(path.name, source)
    return copy.deepcopy(_JS_ADAPTER_RESULTS[key])


def _probe_js_adapter(name: str, source: bytes) -> dict[str, Any]:
    node = shutil.which("node")
    if node is None:
        raise FileNotFoundError("node is required for JavaScript adapter derivation")
    with tempfile.TemporaryDirectory() as tmp:
        module = Path(tmp) / "adapter.mjs"
        module.write_bytes(source)
        proc = subprocess.run(  # noqa: S603 — node and local source under validation
            [node, "--input-type=module", "-", str(module), JS_ADAPTERS[name]],
            input=JS_ADAPTER_PROBE,
            capture_output=True,
            text=True,
            timeout=10,
            env={
                **os.environ,
                "COMPASS_HOME": tmp,
                **({} if sys.platform == "win32" else {"PATH": str(Path(node).parent)}),
            },
            check=False,
        )
    if proc.returncode or proc.stderr:
        raise ValueError(f"{name}: JavaScript callback probe failed: {proc.stderr}")
    result: dict[str, Any] = json.loads(proc.stdout)
    return result


def check_js_adapters(adapter_dir: Path) -> list[str]:
    """Hold native subscription, mapped pair and destination independently."""
    problems = []
    for filename, harness in JS_ADAPTERS.items():
        path = adapter_dir / filename
        try:
            observed = exercise_js_adapter(path)
            expected_hooks = (
                ["event"] if harness == "opencode" else ["ui_prompt_start", "ui_prompt_end"]
            )
            if observed["hooks"] != expected_hooks:
                problems.append(f"{filename}: unexpected native callback registration")
            delivered = observed["deliveries"]
            if [r["body"].get("event") for r in delivered] != ["input_requested", "input_resolved"]:
                problems.append(f"{filename}: native permission pair did not map to a gate pair")
            if any(r["path"] != f"/api/events/{harness}" for r in delivered):
                problems.append(f"{filename}: wrong harness event route")
            names = set(re.findall(r"[\"\'](permission\.[A-Za-z_.]+)[\"\']", path.read_text()))
            if harness == "opencode" and names != {"permission.asked", "permission.replied"}:
                problems.append(f"{filename}: unsupported permission vocabulary")
        except (OSError, ValueError, KeyError, TypeError, subprocess.TimeoutExpired):
            problems.append(f"{filename}: JavaScript adapter could not be exercised")
    return problems


ROOT = Path(__file__).resolve().parents[1]
PLUGIN_NAMES = ("compass",)

# Gemini CLI gets its own extension root rather than sharing the plugin root.
# Both harnesses load extension hooks from `<root>/hooks/hooks.json` and neither
# lets that path be moved: Claude Code reads it whichever path the manifest
# declares, and Gemini's reference states hooks "are not defined in the
# gemini-extension.json manifest". Sharing one root therefore hands each harness
# the other's vocabulary. Measured, before the split: a Gemini session loading
# Claude's file printed eight `Invalid hook event name` warnings, then ran the two
# names that do overlap and reported both as failed hooks, because Gemini does not
# expand `${CLAUDE_PLUGIN_ROOT}` -- at a synchronous cost of 258 ms and 259 ms per
# session for nothing.
GEMINI_EXTENSION_ROOT = "compass-gemini"

# The Gemini extension is self-contained because `gemini extensions install`
# copies the directory and a git-URL install clones it, so a command reaching
# outside the extension root would not resolve once installed. That means two
# scripts ship twice, and drift between the copies is the hazard the byte check
# below exists to prevent.
GEMINI_EXTENSION_FILES = (
    "gemini-extension.json",
    "hooks/hooks.json",
    "hooks/event_hook.py",
    "hooks/notify_hook.py",
)

DROID_EXTENSION_ROOT = "compass-droid"
DROID_EXTENSION_FILES = (
    ".factory-plugin/plugin.json",
    "hooks/hooks.json",
    "hooks/event_hook.py",
    "hooks/notify_hook.py",
)

# Which shipped file is a byte-identical copy of which source of truth.
DUPLICATED_SCRIPTS = (
    (f"{GEMINI_EXTENSION_ROOT}/hooks/event_hook.py", "compass/skills/compass/event_hook.py"),
    (f"{GEMINI_EXTENSION_ROOT}/hooks/notify_hook.py", "compass/skills/compass/notify_hook.py"),
    (f"{DROID_EXTENSION_ROOT}/hooks/event_hook.py", "compass/skills/compass/event_hook.py"),
    (f"{DROID_EXTENSION_ROOT}/hooks/notify_hook.py", "compass/skills/compass/notify_hook.py"),
)
NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
PORTABILITY_MARKERS = {
    "${CLAUDE_PLUGIN_ROOT}": "resolve shared skill resources relative to the skill instead",
    ".claude/skills/": "reference the bundled skill path instead of a user cache",
    "mcp__claude_ai_": "describe the MCP capability instead of a host-specific tool name",
    "ToolSearch(": "describe tool discovery semantically",
    "Skill(skill=": "describe skill invocation semantically",
    "subagent_type": "describe the required worker capability instead of a Claude API field",
}
SHARED_FRONTMATTER_FIELDS = {"name", "description", "license"}
# The skill now carries font software whose OFL terms must survive distribution;
# pinning the expression prevents its metadata from reverting to Apache-only.
SHIPPED_SKILL_LICENSES = {
    ("compass", "compass"): "Apache-2.0 AND OFL-1.1",
}
MAX_CATALOG_TOKEN_ESTIMATE = 4_000
# Prose documentation outside the plugin tree. validate_skills() covers bundled
# skill Markdown; without this list the repository's own docs get no link check
# at all, which is how two of them kept pointing at a dashboard URL the server
# does not serve. CODE_OF_CONDUCT.md is verbatim upstream text and LICENSE and
# NOTICE are not Markdown, so none of them are listed.
ROOT_DOCS = (
    "README.md",
    "MANUAL.md",
    "HOW_TO_USE.md",
    "AGENTS.md",
    "CLAUDE.md",
    "CONTRIBUTING.md",
    "COMPATIBILITY.md",
    "SECURITY.md",
    ".github/PULL_REQUEST_TEMPLATE.md",
)
# The server binds IPv4 loopback only, and on some systems `localhost` resolves
# to ::1 first. Every document says 127.0.0.1; the dashboard tests pin this for the
# shipped SKILL.md, and this pins it for the rest.
BANNED_DOC_LITERALS = {
    "http://localhost:4553": "the server is IPv4-only; write http://127.0.0.1:4553",
}

# Reader-facing documents are restricted by default, including newly created
# Markdown. Development provenance survives only in these explicit areas.
PUBLIC_TRACKER_DEVELOPMENT_FILES = frozenset(
    {
        "AGENTS.md",
        "CLAUDE.md",
        "CONTRIBUTING.md",
        ".github/PULL_REQUEST_TEMPLATE.md",
        "docs/development-tracking.md",
    }
)
PUBLIC_TRACKER_DEVELOPMENT_DIRS = (
    ".claude/skills/",
    ".claude/agents/",
    ".agents/skills/",
    "tests/",
    "docs/plans/",
    "docs/captures/",
    "docs/abstention/",
    "docs/drift-replay/",
    "docs/drift-levels/",
    "docs/feedback/",
    "docs/future-ui-exploration/",
    "docs/roadmap-burndown/",
    "docs/visibility-2x2/",
)
PUBLIC_TRACKER_EVIDENCE_DEVELOPMENT_FILES = frozenset(
    {
        "docs/evidence/intent-and-drift/COLD_STUDY_PROTOCOL.md",
        "docs/evidence/intent-and-drift/RUN_TEMPLATE.md",
    }
)
PUBLIC_TRACKER_EVIDENCE_PUBLIC_FILES = frozenset(
    {
        "docs/evidence/intent-and-drift/README.md",
        "docs/evidence/intent-and-drift/PROMPT.md",
        "docs/evidence/intent-and-drift/PARTICIPANT_KICKOFF.md",
        "docs/promise-map.md",
    }
)
PUBLIC_TRACKER_TOKENS = re.compile(r"\blinear\b|linear\.app|linear://|\bdrc-\d+\b", re.IGNORECASE)
# A lowercase mathematical adjective is not a brand. Keep this explicit and
# narrow: unfamiliar uses can be reworded or reviewed rather than exempting
# lowercase brand mentions or silently weakening the raw-text scan.
PUBLIC_LINEAR_MATH = re.compile(
    r"^\s+(?:scan|time|complexity|scaling|growth|interpolation|algebra|equations?|"
    r"functions?|algorithms?|passes?|combinations?|in\s+the\s+number|JSONL transcript)\b"
)
PUBLIC_DOC_WALK_PRUNE = frozenset({".git", "node_modules", ".venv", "venv", "__pycache__"})


def _public_document(path: Path) -> bool:
    relative = path.relative_to(ROOT).as_posix()
    # Shipped roots win even over a nested development-looking directory.
    if relative.split("/", 1)[0] in {*PLUGIN_NAMES, GEMINI_EXTENSION_ROOT, DROID_EXTENSION_ROOT}:
        return True
    if relative in PUBLIC_TRACKER_EVIDENCE_PUBLIC_FILES:
        return True
    if relative in PUBLIC_TRACKER_DEVELOPMENT_FILES or relative.startswith(
        PUBLIC_TRACKER_DEVELOPMENT_DIRS
    ):
        return False
    if relative.startswith("docs/design-") and "/" not in relative[len("docs/") :]:
        return False
    if relative in PUBLIC_TRACKER_EVIDENCE_DEVELOPMENT_FILES:
        return False
    return not (
        relative.startswith("docs/evidence/intent-and-drift/run-")
        and "/" not in relative[len("docs/evidence/intent-and-drift/") :]
    )


def validate_public_text(path: Path, validation: Validation) -> None:
    """Scan raw content, including code, reference definitions and HTML links."""
    try:
        body = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        validation.error(path, "cannot read public text as UTF-8")
        return
    for match in PUBLIC_TRACKER_TOKENS.finditer(body):
        if match.group() == "linear" and PUBLIC_LINEAR_MATH.match(body[match.end() :]):
            continue
        line = body.count("\n", 0, match.start()) + 1
        validation.error(
            f"{path}:{line}",
            "public text contains a private tracker reference; "
            "remove the brand, host or issue key before publication",
        )


def _public_doc_candidate(path: Path) -> bool:
    return path.suffix.lower() == ".md" or path.name in {"LICENSE", "NOTICE"}


def validate_public_docs(validation: Validation) -> None:
    """Discover nonignored new Markdown and tracked files, pruning private trees."""
    # Union tracked paths before pruning: tracked text stays covered even when a
    # later ignore rule hides its parent from an ordinary filesystem walk.
    paths: set[Path] = set()
    try:
        tracked = subprocess.run(
            ["git", "ls-files", "-z"],  # noqa: S607
            cwd=ROOT,
            capture_output=True,
            check=False,
        )
        if tracked.returncode == 0:
            paths.update(
                ROOT / name
                for name in tracked.stdout.decode("utf-8", errors="surrogateescape").split("\0")
                if name and _public_doc_candidate(Path(name))
            )
    except OSError:
        pass  # Git failure falls back to filesystem discovery, never skips text.
    for directory, children, files in os.walk(ROOT, followlinks=False):
        parent = Path(directory)
        candidates = [
            parent / name
            for name in children
            if name not in PUBLIC_DOC_WALK_PRUNE
            and not (parent.name in {".claude", ".agents"} and name == "worktrees")
        ]
        ignored = _git_ignored(candidates)
        children[:] = [path.name for path in candidates if path not in ignored]
        candidates = [parent / name for name in files if _public_doc_candidate(Path(name))]
        ignored = _git_ignored(candidates)
        paths.update(path for path in candidates if path not in ignored)
    for path in sorted(paths):
        if _public_document(path):
            validate_public_text(path, validation)


def check_public_text(path: Path) -> int:
    """Standalone release-body gate; no checkout inventory or links are needed."""
    validation = Validation()
    validate_public_text(path, validation)
    for error in validation.errors:
        print(f"::error::{error}")
    if validation.errors:
        return 1
    print(f"Public text boundary passed: {path}")
    return 0


class UniqueKeyLoader(yaml.SafeLoader):  # type: ignore[misc]  # PyYAML ships no stubs, so SafeLoader is Any
    """Safe YAML loader that rejects duplicate mapping keys."""


def construct_unique_mapping(
    loader: UniqueKeyLoader, node: yaml.MappingNode, deep: bool = False
) -> dict[object, object]:
    loader.flatten_mapping(node)
    mapping: dict[object, object] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        try:
            duplicate = key in mapping
        except TypeError as exc:
            raise ConstructorError(
                "while constructing a mapping",
                node.start_mark,
                "found an unhashable key",
                key_node.start_mark,
            ) from exc
        if duplicate:
            raise ConstructorError(
                "while constructing a mapping",
                node.start_mark,
                f"found duplicate key {key!r}",
                key_node.start_mark,
            )
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


UniqueKeyLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, construct_unique_mapping
)


# Every file the shipped dashboard needs at runtime, relative to the plugin root.
# The launcher imports compass_runtime.cli, which reaches all of these, so any
# one of them missing from an installed copy is a dashboard that cannot start.
# A packaging step that copies "the skill" without walking subpackages, or an
# archive that drops a frontend asset, both fail here with the exact path.
#
# Kept as an explicit tuple rather than derived from the checkout on purpose: a
# glob would describe whatever happens to be present and could never notice an
# omission.
COMPASS_RUNTIME_FILES = (
    # Codex loads this through the `hooks` key in its manifest, so an install
    # missing it silently reports no Codex events at all rather than failing.
    "hooks/hooks.json",
    "hooks/codex-hooks.json",
    "hooks.json",
    "skills/compass/server.py",
    "skills/compass/notify_hook.py",
    "skills/compass/event_hook.py",
    "skills/compass/statusline_hook.py",
    "skills/compass/agy_hook.py",
    "skills/compass/opencode_plugin.js",
    "skills/compass/pi_extension.js",
    # The stdio MCP server. A top-level `.py` beside the other edge scripts on
    # purpose: the inventory test globs `skills/compass/*.py` non-recursively, so a
    # subdirectory would be invisible here and ship as a broken install.
    "skills/compass/mcp_server.py",
    "skills/compass/compass_runtime/__init__.py",
    "skills/compass/compass_runtime/cli.py",
    "skills/compass/compass_runtime/config.py",
    "skills/compass/compass_runtime/frontend_dev.py",
    "skills/compass/compass_runtime/state.py",
    "skills/compass/compass_runtime/stream.py",
    "skills/compass/compass_runtime/asks.py",
    "skills/compass/compass_runtime/io.py",
    "skills/compass/compass_runtime/probe.py",
    "skills/compass/compass_runtime/records.py",
    "skills/compass/compass_runtime/transcripts.py",
    "skills/compass/compass_runtime/turns.py",
    "skills/compass/compass_runtime/unasked.py",
    "skills/compass/compass_runtime/supervise.py",
    "skills/compass/compass_runtime/reading_jobs.py",
    "skills/compass/compass_runtime/sessions.py",
    "skills/compass/compass_runtime/snapshot.py",
    "skills/compass/compass_runtime/events.py",
    "skills/compass/compass_runtime/irreversible.py",
    "skills/compass/compass_runtime/focus.py",
    "skills/compass/compass_runtime/git_status.py",
    "skills/compass/compass_runtime/history.py",
    "skills/compass/compass_runtime/claude_data.py",
    "skills/compass/compass_runtime/deliveries.py",
    "skills/compass/compass_runtime/departures.py",
    "skills/compass/compass_runtime/ends.py",
    "skills/compass/compass_runtime/dismissals.py",
    "skills/compass/compass_runtime/copied_corrections.py",
    "skills/compass/compass_runtime/correction.py",
    "skills/compass/compass_runtime/notifications.py",
    "skills/compass/compass_runtime/spacedock.py",
    "skills/compass/compass_runtime/tripwires.py",
    "skills/compass/compass_runtime/quota.py",
    "skills/compass/compass_runtime/aggregate.py",
    "skills/compass/compass_runtime/annotations.py",
    "skills/compass/compass_runtime/observation.py",
    "skills/compass/compass_runtime/diagnostics.py",
    "skills/compass/compass_runtime/lifecycle.py",
    "skills/compass/compass_runtime/http_api.py",
    "skills/compass/compass_runtime/observer.py",
    "skills/compass/compass_runtime/reading.py",
    "skills/compass/compass_runtime/reading_policy.py",
    "skills/compass/compass_runtime/reading_route.py",
    "skills/compass/compass_runtime/levels.py",
    "skills/compass/compass_runtime/live_estimate.py",
    "skills/compass/compass_runtime/reach.py",
    "skills/compass/compass_runtime/semantic_history.py",
    "skills/compass/compass_runtime/record_pages.py",
    "skills/compass/compass_runtime/session_source.py",
    "skills/compass/compass_runtime/session_outline.py",
    "skills/compass/compass_runtime/session_summary.py",
    "skills/compass/compass_runtime/summary_store.py",
    "skills/compass/compass_runtime/summary_jobs.py",
    "skills/compass/compass_runtime/entry_numbers.py",
    "skills/compass/compass_runtime/goal_find.py",
    "skills/compass/compass_runtime/interaction_prototype.py",
    "skills/compass/compass_runtime/project_context.py",
    "skills/compass/compass_runtime/collectors/__init__.py",
    "skills/compass/compass_runtime/collectors/claude.py",
    "skills/compass/compass_runtime/collectors/codex.py",
    "skills/compass/compass_runtime/collectors/pi.py",
    "skills/compass/compass_runtime/collectors/gemini.py",
    "skills/compass/compass_runtime/collectors/antigravity.py",
    "skills/compass/compass_runtime/collectors/copilot.py",
    "skills/compass/compass_runtime/collectors/opencode.py",
    "skills/compass/compass_runtime/collectors/cursor.py",
    "skills/compass/compass_runtime/collectors/goose.py",
    "skills/compass/compass_runtime/collectors/droid.py",
    "skills/compass/compass_runtime/web/__init__.py",
    "skills/compass/compass_runtime/web/react.html",
    "skills/compass/compass_runtime/web/react.integrity.json",
    "skills/compass/compass_runtime/web/react-licenses.txt",
    "skills/compass/compass_runtime/web/styles.css",
    "skills/compass/compass_runtime/web/vendor/xterm.js",
    "skills/compass/compass_runtime/web/vendor/xterm.css",
    "skills/compass/compass_runtime/web/vendor/xterm-LICENSE.txt",
    "skills/compass/compass_runtime/web/vendor/SOURCES.txt",
    "skills/compass/compass_runtime/web/fonts/space-grotesk-v22-vietnamese.woff2.b64",
    "skills/compass/compass_runtime/web/fonts/space-grotesk-v22-latin-ext.woff2.b64",
    "skills/compass/compass_runtime/web/fonts/space-grotesk-v22-latin.woff2.b64",
    "skills/compass/compass_runtime/web/fonts/ibm-plex-mono-v20-regular-vietnamese.woff2.b64",
    "skills/compass/compass_runtime/web/fonts/ibm-plex-mono-v20-regular-latin-ext.woff2.b64",
    "skills/compass/compass_runtime/web/fonts/ibm-plex-mono-v20-regular-latin.woff2.b64",
    "skills/compass/compass_runtime/web/fonts/ibm-plex-mono-v20-medium-vietnamese.woff2.b64",
    "skills/compass/compass_runtime/web/fonts/ibm-plex-mono-v20-medium-latin-ext.woff2.b64",
    "skills/compass/compass_runtime/web/fonts/ibm-plex-mono-v20-medium-latin.woff2.b64",
    "skills/compass/compass_runtime/web/fonts/ibm-plex-mono-v20-semibold-vietnamese.woff2.b64",
    "skills/compass/compass_runtime/web/fonts/ibm-plex-mono-v20-semibold-latin-ext.woff2.b64",
    "skills/compass/compass_runtime/web/fonts/ibm-plex-mono-v20-semibold-latin.woff2.b64",
    "skills/compass/compass_runtime/web/fonts/ibm-plex-mono-v20-italic-vietnamese.woff2.b64",
    "skills/compass/compass_runtime/web/fonts/ibm-plex-mono-v20-italic-latin-ext.woff2.b64",
    "skills/compass/compass_runtime/web/fonts/ibm-plex-mono-v20-italic-latin.woff2.b64",
    "skills/compass/compass_runtime/web/fonts/SpaceGrotesk-OFL.txt",
    "skills/compass/compass_runtime/web/fonts/IBMPlexMono-OFL.txt",
    "skills/compass/compass_runtime/web/fonts/SOURCES.txt",
    "skills/compass/compass_runtime/web/page.py",
)


class Validation:
    def __init__(self) -> None:
        self.errors: list[str] = []

    def error(self, path: Path | str, message: str) -> None:
        candidate = Path(path)
        try:
            # Resolve both sides: resolve() rewrites 8.3 short names on Windows
            # and /var -> /private/var on macOS, so comparing a resolved path
            # against an unresolved ROOT raises ValueError for paths that are
            # in fact inside it.
            label = candidate.resolve().relative_to(Path(ROOT).resolve()).as_posix()
        except (TypeError, ValueError, OSError):
            # Genuinely outside ROOT, or unresolvable. Still render with forward
            # slashes so error text reads identically on every platform —
            # str(path) would emit backslashes on Windows.
            label = candidate.as_posix()
        self.errors.append(f"{label}: {message}")


def load_json(path: Path, validation: Validation) -> dict[str, Any] | None:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        validation.error(path, f"cannot read file ({exc})")
        return None
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        validation.error(path, f"invalid JSON ({exc})")
        return None
    if not isinstance(value, dict):
        validation.error(path, "top level must be an object")
        return None
    return value


def load_yaml_mapping(
    text: str, path: Path, validation: Validation, label: str
) -> dict[str, Any] | None:
    try:
        value = yaml.load(text, Loader=UniqueKeyLoader)  # noqa: S506 — SafeLoader subclass
    except yaml.YAMLError as exc:
        validation.error(path, f"invalid {label} YAML ({exc})")
        return None
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        validation.error(path, f"{label} must be a mapping with string keys")
        return None
    return value


def parse_frontmatter(path: Path, validation: Validation) -> dict[str, Any] | None:
    lines = path.read_text(encoding="utf-8").splitlines()
    if not lines or lines[0] != "---":
        validation.error(path, "SKILL.md must begin with YAML frontmatter")
        return None
    try:
        end = lines.index("---", 1)
    except ValueError:
        validation.error(path, "frontmatter is missing its closing delimiter")
        return None

    metadata = load_yaml_mapping("\n".join(lines[1:end]), path, validation, "frontmatter")
    if metadata is None:
        return None
    unknown = set(metadata) - SHARED_FRONTMATTER_FIELDS
    if unknown:
        validation.error(path, f"unsupported shared frontmatter fields: {sorted(unknown)}")
    if "license" in metadata and not isinstance(metadata["license"], str):
        validation.error(path, "frontmatter license must be a string")
    return metadata


def parse_openai_metadata(path: Path, validation: Validation) -> dict[str, Any] | None:
    yaml_text = path.read_text(encoding="utf-8")
    document = load_yaml_mapping(yaml_text, path, validation, "agents/openai.yaml")
    if document is None:
        return None
    unknown_top_level = set(document) - {"interface", "dependencies", "policy"}
    if unknown_top_level:
        validation.error(path, f"unsupported openai.yaml fields: {sorted(unknown_top_level)}")
    interface = document.get("interface")
    if not isinstance(interface, dict) or not all(isinstance(key, str) for key in interface):
        validation.error(path, "interface must be a mapping with string keys")
        return None
    allowed_interface = {
        "display_name",
        "short_description",
        "icon_small",
        "icon_large",
        "brand_color",
        "default_prompt",
    }
    unknown_interface = set(interface) - allowed_interface
    if unknown_interface:
        validation.error(path, f"unsupported interface fields: {sorted(unknown_interface)}")
    for field in allowed_interface:
        if field in interface and (
            not isinstance(interface[field], str) or not interface[field].strip()
        ):
            validation.error(path, f"interface.{field} must be a non-empty string")
    brand_color = interface.get("brand_color")
    if isinstance(brand_color, str) and not re.fullmatch(r"#[0-9A-Fa-f]{6}", brand_color):
        validation.error(path, "interface.brand_color must be a six-digit hex color")

    dependencies = document.get("dependencies")
    if dependencies is not None:
        if not isinstance(dependencies, dict):
            validation.error(path, "dependencies must be a mapping")
        else:
            unknown_dependencies = set(dependencies) - {"tools"}
            if unknown_dependencies:
                validation.error(
                    path,
                    f"unsupported dependencies fields: {sorted(unknown_dependencies)}",
                )
            tools = dependencies.get("tools")
            if not isinstance(tools, list):
                validation.error(path, "dependencies.tools must be a list")
            else:
                allowed_tool_fields = {"type", "value", "description", "transport", "url"}
                for index, tool in enumerate(tools):
                    if not isinstance(tool, dict):
                        validation.error(path, f"dependencies.tools[{index}] must be a mapping")
                        continue
                    unknown_tool_fields = set(tool) - allowed_tool_fields
                    if unknown_tool_fields:
                        validation.error(
                            path,
                            f"dependencies.tools[{index}] has unsupported fields: "
                            f"{sorted(unknown_tool_fields)}",
                        )
                    if tool.get("type") != "mcp":
                        validation.error(path, f"dependencies.tools[{index}].type must be 'mcp'")
                    for field in ("value", "description"):
                        if not isinstance(tool.get(field), str) or not tool[field].strip():
                            validation.error(
                                path,
                                f"dependencies.tools[{index}].{field} must be a non-empty string",
                            )
                    for field in ("transport", "url"):
                        if field in tool and (
                            not isinstance(tool[field], str) or not tool[field].strip()
                        ):
                            validation.error(
                                path,
                                f"dependencies.tools[{index}].{field} must be a non-empty string",
                            )

    policy = document.get("policy")
    if policy is not None:
        if not isinstance(policy, dict):
            validation.error(path, "policy must be a mapping")
        else:
            unknown_policy = set(policy) - {"allow_implicit_invocation"}
            if unknown_policy:
                validation.error(path, f"unsupported policy fields: {sorted(unknown_policy)}")
            if "allow_implicit_invocation" in policy and not isinstance(
                policy["allow_implicit_invocation"], bool
            ):
                validation.error(path, "policy.allow_implicit_invocation must be a boolean")
    return interface


def render_catalog_estimate_line(plugin: str, name: str, description: str, path: Path) -> str:
    """Build the repository's conservative, client-independent catalog estimate."""
    rendered_path = path.relative_to(ROOT).as_posix()
    return f"- {plugin}:{name}: {description} (file: {rendered_path})"


def approx_token_count(text: str) -> int:
    """Apply the repository's conservative four-bytes-per-token policy."""
    return max(1, (len(text.encode("utf-8")) + 3) // 4)


def validate_skill_description(value: object, path: Path, validation: Validation) -> str:
    """Validate the shared catalog description contract."""
    if not isinstance(value, str) or not value:
        validation.error(path, "description is required")
        return ""
    if len(value) > 300:
        validation.error(path, f"description is {len(value)} characters; maximum is 300")
    if "<" in value or ">" in value:
        validation.error(path, "description must not contain angle-bracket placeholders")
    return value


def markdown_prose(text: str) -> str:
    """Blank out YAML frontmatter and fenced code, preserving line positions.

    Both fence styles count. Anything inside them is code, not prose: a link
    there must not be resolved and a `#` there is a comment, not a heading.
    Known gap: four-space indented code blocks are still treated as prose.
    """
    lines = text.splitlines()
    start = 0
    if lines and lines[0].strip() == "---":
        for index in range(1, len(lines)):
            if lines[index].strip() == "---":
                start = index + 1
                break
    out = [""] * min(start, len(lines))
    fence: str | None = None
    for line in lines[start:]:
        marker = re.match(r"\s{0,3}(`{3,}|~{3,})", line)
        if fence is None and marker:
            fence = marker.group(1)[0]
            out.append("")
        elif fence is not None:
            if marker and marker.group(1)[0] == fence:
                fence = None
            out.append("")
        else:
            out.append(line)
    return "\n".join(out)


def slugify_heading(text: str) -> str:
    """Anchor a heading's rendered text the way GitHub does.

    GitHub slugs what the heading *renders* to, so inline links collapse to
    their label and markup characters vanish. Word characters survive —
    including underscores and non-ASCII letters, which a naive `[a-z0-9]`
    filter would silently drop.
    """
    text = re.sub(r"!?\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"<[^>]*>", "", text)
    text = re.sub(r"[^\w\- ]", "", text.strip().lower(), flags=re.UNICODE)
    return text.replace(" ", "-")


def heading_slugs(path: Path) -> set[str]:
    """Every anchor a Markdown file exposes: ATX, Setext, and explicit HTML."""
    body = markdown_prose(path.read_text(encoding="utf-8"))
    lines = body.splitlines()
    slugs: set[str] = set()
    seen: dict[str, int] = {}
    for index, line in enumerate(lines):
        atx = re.match(r"\s{0,3}#{1,6}\s+(.*?)\s*#*$", line)
        if atx:
            title = atx.group(1)
        elif (
            line.strip()
            and index + 1 < len(lines)
            and re.fullmatch(r"\s{0,3}(=+|-{2,})\s*", lines[index + 1])
        ):
            title = line.strip()
        else:
            continue
        base = slugify_heading(title)
        # GitHub disambiguates repeated headings with -1, -2, …
        count = seen.get(base, 0)
        seen[base] = count + 1
        slugs.add(base if count == 0 else f"{base}-{count}")
    slugs.update(re.findall(r"<a\s[^>]*(?:name|id)=[\"']([^\"']+)", body))
    return slugs


# Inline link, with the optional CommonMark title consumed rather than
# swallowed into the destination. Known gap: parentheses inside a bare
# destination are not balanced — wrap such a target in <>.
MARKDOWN_LINK_RE = re.compile(
    r"!?\[[^\]]*\]\(\s*(<[^>]*>|[^\s)]*)(?:\s+(?:\"[^\"]*\"|'[^']*'|\([^)]*\)))?\s*\)"
)


def validate_markdown_links(path: Path, validation: Validation) -> None:
    prose = markdown_prose(path.read_text(encoding="utf-8"))
    for raw_target in MARKDOWN_LINK_RE.findall(prose):
        stripped = raw_target.strip().strip("<>")
        if stripped.startswith(("http://", "https://", "mailto:")):
            continue
        target, _, fragment = stripped.partition("#")
        if not target:
            # Same-file anchor: resolve it against this file's own headings.
            if fragment and fragment not in heading_slugs(path):
                validation.error(path, f"Markdown anchor does not exist: {raw_target}")
            continue
        # Bare prose placeholders such as `(url)` are not filesystem links.
        if "/" not in target and not Path(target).suffix:
            continue
        resolved = (path.parent / target).resolve()
        try:
            resolved.relative_to(ROOT)
        except ValueError:
            validation.error(path, f"Markdown link escapes the repository: {raw_target}")
            continue
        if not resolved.exists():
            validation.error(path, f"Markdown link target does not exist: {raw_target}")
            continue
        # A fragment that points at a heading which no longer exists is a
        # dangling link the reader only discovers by clicking it.
        if fragment and resolved.suffix == ".md" and fragment not in heading_slugs(resolved):
            validation.error(path, f"Markdown anchor does not exist: {raw_target}")


def resolve_contract_path(
    plugin_root: Path, raw_path: object, field: str, manifest_path: Path, validation: Validation
) -> Path | None:
    if not isinstance(raw_path, str) or not raw_path.startswith("./"):
        validation.error(manifest_path, f"{field} must be an ./-prefixed relative path")
        return None
    resolved = (plugin_root / raw_path).resolve()
    try:
        resolved.relative_to(plugin_root.resolve())
    except ValueError:
        validation.error(manifest_path, f"{field} must stay inside the plugin root")
        return None
    if not resolved.exists():
        validation.error(manifest_path, f"{field} path does not exist: {raw_path}")
    return resolved


def validate_mcp_entries(entries: object, path: Path, validation: Validation) -> None:
    if not isinstance(entries, dict) or not entries:
        validation.error(path, "MCP server map must be a non-empty object")
        return
    for name, config in entries.items():
        if not isinstance(name, str) or not name:
            validation.error(path, "MCP server names must be non-empty strings")
        if not isinstance(config, dict):
            validation.error(path, f"MCP server {name!r} must be an object")
            continue
        if not any(key in config for key in ("url", "command")):
            validation.error(path, f"MCP server {name!r} needs a url or command")


def validate_codex_manifest(plugin_root: Path, validation: Validation) -> dict[str, Any] | None:
    path = plugin_root / ".codex-plugin/plugin.json"
    manifest = load_json(path, validation)
    if manifest is None:
        return None

    for field in ("name", "version", "description"):
        if not isinstance(manifest.get(field), str) or not manifest[field].strip():
            validation.error(path, f"{field} must be a non-empty string")
    if manifest.get("name") != plugin_root.name:
        validation.error(path, "name must match the plugin directory")
    resolve_contract_path(plugin_root, manifest.get("skills"), "skills", path, validation)

    interface = manifest.get("interface")
    if not isinstance(interface, dict):
        validation.error(path, "interface metadata is required by repository policy")
    else:
        for field in ("displayName", "shortDescription", "longDescription", "developerName"):
            if not isinstance(interface.get(field), str) or not interface[field].strip():
                validation.error(path, f"interface.{field} must be a non-empty string")
        capabilities = interface.get("capabilities")
        if not isinstance(capabilities, list) or "Read" not in capabilities:
            validation.error(path, "interface.capabilities must include Read")
        prompts = interface.get("defaultPrompt")
        if not isinstance(prompts, list) or not 1 <= len(prompts) <= 3:
            validation.error(path, "interface.defaultPrompt must contain one to three prompts")
        elif any(
            not isinstance(prompt, str) or not prompt.strip() or len(prompt) > 128
            for prompt in prompts
        ):
            validation.error(
                path, "default prompts must be non-empty strings of at most 128 characters"
            )

    mcp_servers = manifest.get("mcpServers")
    if isinstance(mcp_servers, dict):
        validate_mcp_entries(mcp_servers, path, validation)
    elif isinstance(mcp_servers, str):
        mcp_path = resolve_contract_path(plugin_root, mcp_servers, "mcpServers", path, validation)
        if mcp_path and mcp_path.is_file():
            config = load_json(mcp_path, validation)
            if config is not None:
                entries = config.get("mcp_servers", config.get("mcpServers", config))
                validate_mcp_entries(entries, mcp_path, validation)
    elif mcp_servers is not None:
        validation.error(path, "mcpServers must be a path or server map")
    return manifest


def validate_antigravity_manifest(
    plugin_root: Path, validation: Validation
) -> dict[str, Any] | None:
    path = plugin_root / "plugin.json"
    manifest = load_json(path, validation)
    if manifest is None:
        return None

    allowed_fields = {"$schema", "name", "description"}
    unknown_fields = set(manifest) - allowed_fields
    if unknown_fields:
        validation.error(path, f"unsupported Antigravity manifest fields: {sorted(unknown_fields)}")
    for field in ("name", "description"):
        if not isinstance(manifest.get(field), str) or not manifest[field].strip():
            validation.error(path, f"{field} must be a non-empty string")
    if manifest.get("name") != plugin_root.name:
        validation.error(path, "name must match the plugin directory")
    return manifest


def validate_gemini_extension(
    extension_root: Path, expected_name: str, validation: Validation
) -> dict[str, Any] | None:
    """The Gemini extension manifest, which lives in its own root.

    `expected_name` rather than the directory name: the extension installs and is
    listed as `compass`, the same name as the plugin, while its directory is
    `compass-gemini` so that its `hooks/hooks.json` cannot collide with Claude's.
    """
    path = extension_root / "gemini-extension.json"
    manifest = load_json(path, validation)
    if manifest is None:
        return None

    for field in ("name", "version", "description"):
        if not isinstance(manifest.get(field), str) or not manifest[field].strip():
            validation.error(path, f"{field} must be a non-empty string")
    if manifest.get("name") != expected_name:
        validation.error(path, f"name must be {expected_name!r}, matching the plugin")
    for relative in GEMINI_EXTENSION_FILES:
        if not (extension_root / relative).is_file():
            validation.error(extension_root / relative, "missing from the Gemini extension")
    if "mcpServers" in manifest:
        validate_mcp_entries(manifest["mcpServers"], path, validation)
    return manifest


def validate_droid_extension(
    extension_root: Path, expected_name: str, validation: Validation
) -> dict[str, Any] | None:
    """The Droid plugin manifest, which lives in its own root.

    Lives in `compass-droid` so its hooks file cannot collide with Claude's.
    """
    path = extension_root / ".factory-plugin" / "plugin.json"
    manifest = load_json(path, validation)
    if manifest is None:
        return None

    for field in ("name", "description"):
        if not isinstance(manifest.get(field), str) or not manifest[field].strip():
            validation.error(path, f"{field} must be a non-empty string")
    if manifest.get("name") != expected_name:
        validation.error(path, f"name must be {expected_name!r}, matching the plugin")
    for relative in DROID_EXTENSION_FILES:
        if not (extension_root / relative).is_file():
            validation.error(extension_root / relative, "missing from the Droid extension")
    return manifest


def validate_antigravity_mcp_config(
    plugin_root: Path, validation: Validation
) -> dict[str, Any] | None:
    path = plugin_root / "mcp_config.json"
    if not path.is_file():
        return None
    config = load_json(path, validation)
    if config is None:
        return None
    servers = config.get("mcpServers")
    if not isinstance(servers, dict) or not servers:
        validation.error(path, "mcpServers must be a non-empty object")
        return config
    for name, entry in servers.items():
        if (
            not isinstance(entry, dict)
            or not isinstance(entry.get("serverUrl"), str)
            or not entry["serverUrl"].strip()
        ):
            validation.error(path, f"MCP server {name!r} must define a non-empty serverUrl")
    return config


def validate_mcp_endpoint_parity(
    plugin_root: Path,
    gemini_manifest: dict[str, Any] | None,
    mcp_config: dict[str, Any] | None,
    validation: Validation,
) -> None:
    """Every runtime-specific copy of the MCP endpoint must mirror .mcp.json."""
    base_path = plugin_root / ".mcp.json"
    if not base_path.is_file():
        if gemini_manifest is not None and "mcpServers" in gemini_manifest:
            validation.error(
                plugin_root / "gemini-extension.json",
                "declares MCP servers but the plugin has no .mcp.json to mirror",
            )
        if mcp_config is not None:
            validation.error(
                plugin_root / "mcp_config.json",
                "exists but the plugin has no .mcp.json to mirror",
            )
        return
    base = load_json(base_path, validation)
    if base is None or not isinstance(base.get("mcpServers"), dict):
        return
    base_urls = {
        name: entry.get("url")
        for name, entry in base["mcpServers"].items()
        if isinstance(entry, dict)
    }

    def compare(servers: object, url_key: str, path: Path) -> None:
        found: dict[str, Any] = {}
        if isinstance(servers, dict):
            found = {
                name: entry.get(url_key)
                for name, entry in servers.items()
                if isinstance(entry, dict)
            }
        if found != base_urls:
            validation.error(
                path,
                f"MCP endpoints must mirror .mcp.json ({base_urls}); found {found}",
            )

    if gemini_manifest is not None:
        compare(gemini_manifest.get("mcpServers"), "url", plugin_root / "gemini-extension.json")
    if mcp_config is not None:
        compare(mcp_config.get("mcpServers"), "serverUrl", plugin_root / "mcp_config.json")
    else:
        validation.error(
            plugin_root / "mcp_config.json",
            "Antigravity MCP config must exist and mirror .mcp.json",
        )


# Where each harness looks for the hooks this plugin bundles. Verified by running
# each harness against an installed or --plugin-dir copy, not read off a page:
# Claude loads `hooks/hooks.json` by convention, Codex loads whatever path its
# manifest's `hooks` key names, and Antigravity loads a root `hooks.json`.
BUNDLED_HOOKS_FILES = (
    "hooks/hooks.json",
    "hooks/codex-hooks.json",
    "hooks.json",
)

# Which harness reads each bundled hooks file, and every event name that harness
# recognises. Listed explicitly rather than derived from `event_hook.py`, because
# the failure this catches is a *name the harness rejects*, and the adapter's own
# table cannot describe that: a file may legitimately register names the adapter
# does not map, but never a name the harness has never heard of.
#
# The Gemini row is why this exists. Before the root split, Claude's file sat where
# Gemini looks and eight of its ten names were rejected on every Gemini session.
HOOK_FILE_VOCABULARY = {
    "compass/hooks/hooks.json": (
        "claude",
        frozenset(
            {
                "SessionStart",
                "SessionEnd",
                "UserPromptSubmit",
                "Stop",
                "PermissionRequest",
                "Notification",
                "PreToolUse",
                "PostToolUse",
                "SubagentStart",
                "SubagentStop",
                "TaskCompleted",
                "PreCompact",
                "PostCompact",
            }
        ),
    ),
    "compass/hooks/codex-hooks.json": (
        "codex",
        frozenset(
            {
                "SessionStart",
                "SessionEnd",
                "UserPromptSubmit",
                "Stop",
                "PreToolUse",
                "PostToolUse",
                "SubagentStart",
                "SubagentStop",
                "PreCompact",
                "PostCompact",
                # Recognised, and measured as such: a hooks file listing it beside
                # the seven mapped names installed cleanly and left all seven
                # firing. `CODEX_EVENTS` now maps it too -- driven interactively on
                # 0.149.0 it fires with a real gate open and carries `session_id`,
                # and the `codex exec` negative that kept it unmapped turned out to
                # be a property of that mode, which pins `approval_policy` to
                # `never` so nothing ever asks.
                "PermissionRequest",
            }
        ),
    ),
    "compass/hooks.json": (
        "antigravity",
        frozenset({"PreInvocation", "PostInvocation", "PreToolUse", "PostToolUse"}),
    ),
    f"{GEMINI_EXTENSION_ROOT}/hooks/hooks.json": (
        "gemini",
        # The whole documented 0.53.1 vocabulary. This is an allowlist of names
        # the harness recognises, so it is deliberately wider than what was seen:
        # ten of these fired in `docs/captures/gemini/hooks-0.53.1-macos.jsonl`,
        # and `Notification` did not, across 56 invocations. Non-interactive
        # Gemini withholds every tool that needs approval, so nothing could ask.
        # Registering it is still legal; what is not evidenced is its payload.
        frozenset(
            {
                "SessionStart",
                "SessionEnd",
                "BeforeAgent",
                "AfterAgent",
                "BeforeModel",
                "BeforeToolSelection",
                "AfterModel",
                "BeforeTool",
                "AfterTool",
                "Notification",
                "PreCompress",
            }
        ),
    ),
    f"{DROID_EXTENSION_ROOT}/hooks/hooks.json": (
        "droid",
        # Only SessionStart and SessionEnd were measured in Droid 0.202.0 exec.
        # Notification was never captured, and interactive launches did not pass
        # login, so no permission/gate events are mapped.
        frozenset({"SessionStart", "SessionEnd"}),
    ),
}


def validate_hook_vocabulary(validation: Validation) -> None:
    """No bundled hooks file registers a name its harness does not know.

    Two failures, both observed rather than imagined:

    1. A foreign event name. The harness skips it with a warning on every session,
       so the hook silently reports nothing while looking installed.
    2. A foreign harness argument. `event_hook.py claude` in Gemini's file would
       post Gemini sessions to `/api/events/claude`, where Claude's normalizer
       truncates the id to eight characters and it matches no row.

    This validator is keyed by file path to exactly one intended harness vocabulary.
    It states in its own contract that it cannot cover a file two harnesses read: if
    a second harness also loads a file written for the first, this check cannot
    attest that the file is safe or appropriate for that second harness. That
    collision was measured when Droid loaded Claude's hooks.json and ran its hooks
    with `claude` argv (DRC-4208); dedicated extension roots prevent that collision.
    """
    for relative, (harness, vocabulary) in HOOK_FILE_VOCABULARY.items():
        path = ROOT / relative
        if not path.is_file():
            continue
        document = load_json(path, validation)
        if not isinstance(document, dict):
            continue
        for name in _hook_events(document):
            if name not in vocabulary:
                validation.error(
                    path,
                    f"registers {name!r}, which {harness} does not recognise; "
                    f"a foreign event name is skipped with a warning on every session",
                )
        for command in _hook_commands(_hook_events(document)):
            if "event_hook.py" not in command:
                continue
            named = command.rsplit('"', 1)[-1].strip().split(" ")
            if named and named[0] and named[0] != harness:
                validation.error(
                    path,
                    f"hook command passes harness {named[0]!r} in {harness}'s hooks file; "
                    "events would post to the wrong route",
                )


def validate_antigravity_hook_nesting(validation: Validation) -> None:
    """Antigravity's hooks file wraps its events in a name, and a flat one is dead.

    This exists because the flat shape is not a JSON error, is not a schema error
    to `agy plugin validate`, and produces no user-visible failure at run time. It
    is only visible as a warning in `~/.gemini/antigravity-cli/log/`, which nobody
    reads, followed by `loaded 0 named hooks from 0 hooks.json file(s)`.

    Compass shipped the flat shape and its Antigravity hooks therefore never ran.
    Nothing caught it for the whole life of that adapter: `agy plugin validate`
    said `hooks: 5 processed` because it counts top-level keys, this repository's
    own validator read those keys as event names, and the design note recorded
    that difference as a discovered fact rather than a bug. The name-wrapped file
    reports `hooks: 1 processed` instead, so the count going DOWN is the signal
    that it is now right.
    """
    for relative, (harness, _vocabulary) in HOOK_FILE_VOCABULARY.items():
        if harness != "antigravity":
            continue
        path = ROOT / relative
        if not path.is_file():
            continue
        document = load_json(path, validation)
        if not isinstance(document, dict):
            continue
        flat = sorted(key for key, value in document.items() if isinstance(value, list))
        if flat:
            validation.error(
                path,
                f"puts event name(s) {', '.join(flat)} at the top level; Antigravity "
                "requires each top-level key to be a hook NAME with the events nested "
                'inside it, as in {"compass": {"PostToolUse": [...]}}. A flat file '
                "parses, passes `agy plugin validate`, and is discarded at run time",
            )
        if not any(isinstance(value, dict) for value in document.values()):
            validation.error(path, "registers no named hook, so nothing would load")


def validate_duplicated_scripts(validation: Validation) -> None:
    """A script that ships twice is byte-identical in both places.

    The Gemini extension cannot reach outside its own root once installed, so it
    carries its own copy of the adapter and of the transport it imports. Copies
    drift silently; a byte comparison is the only check that does not.
    """
    for copy_relative, source_relative in DUPLICATED_SCRIPTS:
        copy_path = ROOT / copy_relative
        source_path = ROOT / source_relative
        if not copy_path.is_file() or not source_path.is_file():
            continue
        if copy_path.read_bytes() != source_path.read_bytes():
            validation.error(
                copy_path,
                f"must be byte-identical to {source_relative}; "
                f"run: cp {source_relative} {copy_relative}",
            )


def validate_hooks_adapter(plugin_root: Path, validation: Validation) -> None:
    """Every bundled hooks file is well formed and points at a script that ships.

    This used to require the root `hooks.json` to mirror `hooks/hooks.json` byte
    for byte, on the assumption that one hooks file could serve both Claude and
    Antigravity. That assumption is now false in two ways, so the rule is gone
    rather than worked around:

    1. The event vocabularies differ. Claude fires `UserPromptSubmit` and
       `SessionEnd`; Antigravity fires `PreInvocation` and `PostInvocation`. A
       file that satisfies one registers mostly-dead entries in the other.
    2. The command names its harness. `event_hook.py claude` posts to
       `/api/events/claude`, so a mirrored file would make Antigravity sessions
       post as Claude, where the id would be truncated by Claude's normalizer and
       match no row.

    What replaces it is a check byte parity never made: that every command
    references a file this plugin actually ships. A hooks file pointing at a
    missing script installs cleanly and reports nothing, which is the same silent
    failure the runtime inventory exists to prevent.
    """
    for relative in BUNDLED_HOOKS_FILES:
        path = plugin_root / relative
        if not path.is_file():
            continue
        document = load_json(path, validation)
        if document is None or not isinstance(document, dict):
            continue
        events = _hook_events(document)
        if not events:
            validation.error(path, "bundled hooks file registers no events")
            continue
        for command in _hook_commands(events):
            for script in _referenced_plugin_paths(command):
                if not (plugin_root / script).is_file():
                    validation.error(path, f"hook command references missing {script}")


def _hook_events(document: dict[str, Any]) -> dict[str, Any]:
    """The event map, whichever of the two shipped schemas this file uses.

    Claude and Codex wrap the events in a `hooks` object. Antigravity wraps them
    in a **name** instead: each top-level key is a hook name the author chooses,
    like the guide's own `lint-checker`, and the event keys live one level inside
    it.

    An earlier version of this function read Antigravity's top-level keys as event
    names, and the reason it survived is worth keeping: `agy plugin validate`
    counted those keys without type-checking them and reported `hooks: 5
    processed`, so a flattened file looked accepted. It was not. agy's runtime
    rejects it outright, logging `cannot unmarshal array into Go struct field
    .PreToolUse of type jsonhook.JSONHookSpec` and then `loaded 0 named hooks from
    0 hooks.json file(s)`. Measured in
    `docs/captures/antigravity/hooks-schema-1.1.19-macos.jsonl`; the wrapper is
    mandatory and `validate_antigravity_hook_nesting` is what now enforces it.
    """
    wrapped = document.get("hooks")
    if isinstance(wrapped, dict):
        return wrapped
    events: dict[str, Any] = {}
    for value in document.values():
        if isinstance(value, dict):
            events.update({k: v for k, v in value.items() if isinstance(v, list)})
    return events


def _hook_commands(events: Any) -> list[str]:
    """Every command string in a hooks document, in either handler layout.

    Two layouts ship, and Antigravity uses both in one file. Tool-scoped events
    group their handlers under a `matcher`; its loop-scoped events list handlers
    directly. A walker that understood only the grouped form would silently check
    nothing in the flat half.
    """
    found: list[str] = []
    for entries in events.values():
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            if isinstance(entry.get("command"), str):
                found.append(entry["command"])  # flat: a handler directly
            found.extend(
                hook["command"]
                for hook in entry.get("hooks") or []
                if isinstance(hook, dict) and isinstance(hook.get("command"), str)
            )
    return found


def _referenced_plugin_paths(command: str) -> list[str]:
    """Plugin-relative paths a command names through a plugin-root variable.

    Both harnesses expand a variable rather than a literal path, which is what
    keeps the command stable across upgrades: Codex records a trust hash over the
    hook definition, so a command carrying a version number would re-prompt every
    time the plugin updated.
    """
    paths: list[str] = []
    for marker in (
        "${CLAUDE_PLUGIN_ROOT}/",
        "${PLUGIN_ROOT}/",
        "${extensionPath}/",
        "${DROID_PLUGIN_ROOT}/",
    ):
        start = 0
        while (found := command.find(marker, start)) != -1:
            rest = command[found + len(marker) :]
            # Ends at the closing quote or the next whitespace, whichever is first.
            end = min((i for i in (rest.find('"'), rest.find(" ")) if i != -1), default=len(rest))
            paths.append(rest[:end])
            start = found + len(marker)
    return paths


def validate_description_parity(
    plugin_name: str,
    descriptions: dict[str, str | None],
    validation: Validation,
) -> None:
    """Every manifest that carries a description must carry the same one."""
    present = {label: value for label, value in descriptions.items() if value is not None}
    if len(set(present.values())) > 1:
        drifted = ", ".join(sorted(present))
        validation.error(
            ROOT / plugin_name,
            f"description drift across manifests ({drifted}); "
            "align them with .claude-plugin/plugin.json",
        )


def validate_runtime_files(plugin_root: Path, validation: Validation) -> None:
    """Every runtime file the installed dashboard needs is present and is a file.

    is_file() rather than exists(): a directory where a module belongs is a
    packaging bug that reads as "present" to exists() and then fails at import,
    which is much harder to diagnose from an installed copy than from here.
    """
    for relative in COMPASS_RUNTIME_FILES:
        target = plugin_root / relative
        if target.is_file():
            continue
        reason = "must be a file, not a directory" if target.is_dir() else "is missing"
        validation.error(target, f"required runtime file {reason}")


def validate_skills(plugin_root: Path, validation: Validation) -> tuple[set[str], list[str]]:
    skills_root = plugin_root / "skills"
    names: set[str] = set()
    catalog_lines: list[str] = []
    for path in sorted(skills_root.glob("*/SKILL.md")):
        metadata = parse_frontmatter(path, validation)
        if metadata is None:
            continue
        raw_name = metadata.get("name", "")
        name = raw_name if isinstance(raw_name, str) else path.parent.name
        description = metadata.get("description", "")
        if not isinstance(raw_name, str) or not NAME_RE.fullmatch(raw_name):
            validation.error(path, "name must use lowercase kebab-case")
        if isinstance(raw_name, str) and raw_name != path.parent.name:
            validation.error(path, "frontmatter name must match its directory")
        if name in names:
            validation.error(path, f"duplicate skill name {name!r}")
        names.add(name)
        expected_license = SHIPPED_SKILL_LICENSES.get((plugin_root.name, name))
        if expected_license is not None and metadata.get("license") != expected_license:
            validation.error(path, f"frontmatter license must be {expected_license!r}")
        description = validate_skill_description(description, path, validation)
        catalog_lines.append(
            render_catalog_estimate_line(plugin_root.name, name, description, path)
        )
        openai_path = path.parent / "agents/openai.yaml"
        if not openai_path.is_file():
            validation.error(
                openai_path, "Codex presentation metadata is required by repository policy"
            )
        else:
            fields = parse_openai_metadata(openai_path, validation)
            if fields is None:
                continue
            for field in ("display_name", "short_description", "default_prompt"):
                if not isinstance(fields.get(field), str) or not fields[field].strip():
                    validation.error(
                        openai_path, f"interface.{field} must be a quoted non-empty string"
                    )
            short_description = fields.get("short_description", "")
            if (
                isinstance(short_description, str)
                and short_description
                and not 25 <= len(short_description) <= 64
            ):
                validation.error(
                    openai_path, "interface.short_description must be 25 to 64 characters"
                )
            default_prompt = fields.get("default_prompt", "")
            if isinstance(default_prompt, str) and f"${name}" not in default_prompt:
                validation.error(openai_path, f"interface.default_prompt must mention ${name}")

    # References and operation modules are shipped with the skill just like
    # SKILL.md. Validate every bundled Markdown resource so a top-level skill
    # cannot route an agent into a missing or repository-external file.
    for resource_path in sorted(
        path for path in skills_root.rglob("*") if path.is_file() and path.suffix.lower() == ".md"
    ):
        validate_markdown_links(resource_path, validation)
        validate_public_text(resource_path, validation)
        body = resource_path.read_text(encoding="utf-8")
        for marker, guidance in PORTABILITY_MARKERS.items():
            if marker in body:
                validation.error(resource_path, f"shared skill contains {marker!r}; {guidance}")

    if not names:
        validation.error(skills_root, "no skills discovered")
    return names, catalog_lines


def validate_marketplaces(
    codex_manifests: dict[str, dict[str, Any] | None],
    gemini_manifests: dict[str, dict[str, Any] | None],
    antigravity_manifests: dict[str, dict[str, Any] | None],
    validation: Validation,
) -> None:
    codex_path = ROOT / ".agents/plugins/marketplace.json"
    codex_marketplace = load_json(codex_path, validation)
    if codex_marketplace is not None:
        entries = codex_marketplace.get("plugins")
        if not isinstance(entries, list):
            validation.error(codex_path, "plugins must be an array")
        else:
            names: set[str] = set()
            for entry in entries:
                if not isinstance(entry, dict):
                    validation.error(codex_path, "each plugin entry must be an object")
                    continue
                name = entry.get("name")
                names.add(name) if isinstance(name, str) else None
                source = entry.get("source")
                if not isinstance(source, dict) or source.get("source") != "local":
                    validation.error(codex_path, f"{name}: expected a local source object")
                    continue
                resolve_contract_path(
                    ROOT, source.get("path"), f"{name} source", codex_path, validation
                )
            if names != set(PLUGIN_NAMES):
                validation.error(codex_path, f"plugin names must be {sorted(PLUGIN_NAMES)}")

    # compass is listed in spacedock-dev/marketplace, not in a marketplace of
    # its own, so there is no repository-level Claude marketplace to check.
    # Version and description parity is asserted directly across the manifests
    # the plugin ships with; compass/.claude-plugin/plugin.json is the source
    # of truth that bump_version.py writes from.
    for name in PLUGIN_NAMES:
        claude_manifest_path = ROOT / name / ".claude-plugin/plugin.json"
        claude_manifest = load_json(claude_manifest_path, validation)
        if claude_manifest is not None and claude_manifest.get("name") != name:
            validation.error(claude_manifest_path, "name must match the plugin directory")
        codex_manifest = codex_manifests.get(name)
        gemini_manifest = gemini_manifests.get(name)
        versions = {
            claude_manifest.get("version") if claude_manifest else None,
            codex_manifest.get("version") if codex_manifest else None,
            gemini_manifest.get("version") if gemini_manifest else None,
        }
        if len(versions) != 1:
            validation.error(
                claude_manifest_path,
                f"{name} version fields are not in parity: {sorted(map(str, versions))}",
            )
        antigravity_manifest = antigravity_manifests.get(name)
        validate_description_parity(
            name,
            {
                ".claude-plugin/plugin.json": (
                    claude_manifest.get("description") if claude_manifest else None
                ),
                ".codex-plugin/plugin.json": (
                    codex_manifest.get("description") if codex_manifest else None
                ),
                "gemini-extension.json": (
                    gemini_manifest.get("description") if gemini_manifest else None
                ),
                "plugin.json": (
                    antigravity_manifest.get("description") if antigravity_manifest else None
                ),
            },
            validation,
        )


def _git_ignored(paths: list[Path]) -> set[Path]:
    """The subset of `paths` that git is told to ignore.

    `docs/` holds more than source: vendored Spacedock mods, the linked worktree
    of the entity-state orphan branch, and a person's local deep-dive notes. All
    three are gitignored, and 56 of the 78 Markdown files under `docs/` were of
    that kind when this was measured. Walking them made the canonical pre-PR
    validator fail on a vendored file's unexpanded `{state-owner}` placeholders
    for anyone with the mods installed, while CI stayed green because that
    directory is never checked in — a red that belonged to no change.

    `check-ignore` rather than `ls-files`, so a doc that is merely new still gets
    validated before it is staged. Fails open: any git error validates
    everything, which is the behaviour this replaces and can only over-check.
    NUL-delimited UTF-8 paths avoid Git C-quoting, Windows locale decoding and
    newline translation. Forward slashes preserve Windows absolute paths.
    """
    if not paths:
        return set()
    try:
        result = subprocess.run(
            ["git", "check-ignore", "-z", "--stdin"],  # noqa: S607
            cwd=ROOT,
            input=b"\0".join(
                path.as_posix().encode("utf-8", errors="surrogateescape") for path in paths
            )
            + b"\0",
            capture_output=True,
            check=False,
        )
    except OSError:
        return set()
    # 0 = at least one ignored, 1 = none ignored; anything else is a real error.
    if result.returncode not in (0, 1):
        return set()
    return {
        Path(name)
        for name in result.stdout.decode("utf-8", errors="surrogateescape").split("\0")
        if name
    }


def validate_repo_docs(validation: Validation) -> None:
    """Resolve Markdown inline links and anchors in the repository's prose docs.

    Bundled skill Markdown is covered by validate_skills(); this covers
    everything a documentation-sync pass is allowed to edit outside it. It
    catches inline `[text](target)` links only — a backticked path in a table,
    a reference-style link definition, or a path named in a Python comment is
    not checked here.
    """
    paths = [ROOT / name for name in ROOT_DOCS]
    walked = sorted((ROOT / "docs").rglob("*.md"))
    paths.extend(path for path in walked if path not in _git_ignored(walked))
    # Repository development skills. Not shipped, so the portability markers
    # they document are legal there — but their links still have to resolve.
    paths.extend(sorted(ROOT.glob(".claude/skills/*/SKILL.md")))
    for path in paths:
        if not path.is_file():
            validation.error(path, "documented repository file is missing")
            continue
        validate_markdown_links(path, validation)
        body = path.read_text(encoding="utf-8")
        for literal, guidance in BANNED_DOC_LITERALS.items():
            if literal in body:
                validation.error(path, f"contains {literal!r}; {guidance}")


def validate_promise_parity(validation: Validation) -> None:
    """Hold the two in-repo copies of each user-facing promise to each other.

    The same five sentences live in `docs/promise-map.md`, in the Visibility 2x2
    board's `items.json`, and in the Linear project overview. Nothing checked
    them, and one drifted far enough to promise a burn-rate projection the
    project had decided three times not to build, plus a per-session cost figure
    that has never been rendered.

    Not a byte comparison, and the exception is exactly one character: the map's
    sentence continues from its promise lead-in and opens lowercase, while the
    board renders it standing alone and opens with a capital. Keyed by the P
    number against column order rather than by set membership, because the board
    numbers its promises positionally, so reordering the columns would otherwise
    renumber every promise silently.

    Two copies is all this can bind. The third is in Linear, out of reach of any
    check here, and reading it is a person's job.
    """
    map_path = ROOT / "docs/promise-map.md"
    board_path = ROOT / "docs/visibility-2x2/items.json"
    if not map_path.is_file() or not board_path.is_file():
        validation.error(map_path, "the promise map and the board must both exist")
        return
    promises = {
        match.group(1): " ".join(match.group(2).split())
        for match in re.finditer(
            r"^### (P\d)\..*?\n\n\*\*We promise:\*\* (.*?)\n\n",
            map_path.read_text(encoding="utf-8"),
            re.DOTALL | re.MULTILINE,
        )
    }
    board = load_json(board_path, validation)
    if board is None:
        return
    columns = board.get("columns") if isinstance(board, dict) else None
    if not isinstance(columns, list):
        validation.error(board_path, "the board must carry a columns list")
        return
    if len(columns) != len(promises):
        validation.error(
            board_path,
            f"{len(columns)} board columns against {len(promises)} promises in the map",
        )
        return
    for index, column in enumerate(columns, start=1):
        key = f"P{index}"
        expected = promises.get(key)
        if expected is None:
            validation.error(map_path, f"the map has no {key} promise")
            continue
        found = column.get("promise") if isinstance(column, dict) else None
        if found != expected[:1].upper() + expected[1:]:
            validation.error(
                board_path,
                f"{key} disagrees with the promise map; the map is canonical. "
                "A board editing session writes this file through its own save "
                "endpoint, so that is the likely cause",
            )


def validate_repository_skills(validation: Validation) -> None:
    """Repository skills stay canonical for Claude and aliased for Codex.

    Both harnesses discover a convention-named directory. Requiring relative
    symlinks keeps one editable skill body and makes each alias survive a clone
    or a linked worktree at a different absolute path.
    """
    claude_root = ROOT / ".claude/skills"
    codex_root = ROOT / ".agents/skills"
    canonical = (
        {
            path.name: path
            for path in claude_root.iterdir()
            if path.is_dir() and (path / "SKILL.md").is_file()
        }
        if claude_root.is_dir()
        else {}
    )
    if not canonical:
        validation.error(claude_root, "no canonical repository skills discovered")

    for name, skill_root in sorted(canonical.items()):
        skill_path = skill_root / "SKILL.md"
        metadata = parse_frontmatter(skill_path, validation)
        if metadata is not None:
            raw_name = metadata.get("name")
            description = metadata.get("description")
            if not isinstance(raw_name, str) or not NAME_RE.fullmatch(raw_name):
                validation.error(skill_path, "name must use lowercase kebab-case")
            elif raw_name != name:
                validation.error(skill_path, "frontmatter name must match its directory")
            validate_skill_description(description, skill_path, validation)

        openai_path = skill_root / "agents/openai.yaml"
        if not openai_path.is_file():
            validation.error(
                openai_path,
                "Codex presentation metadata is required for repository development skills",
            )
        else:
            fields = parse_openai_metadata(openai_path, validation)
            if fields is not None:
                for field in ("display_name", "short_description", "default_prompt"):
                    if not isinstance(fields.get(field), str) or not fields[field].strip():
                        validation.error(
                            openai_path, f"interface.{field} must be a quoted non-empty string"
                        )
                short_description = fields.get("short_description")
                if isinstance(short_description, str) and not 25 <= len(short_description) <= 64:
                    validation.error(
                        openai_path, "interface.short_description must be 25 to 64 characters"
                    )
                default_prompt = fields.get("default_prompt")
                if isinstance(default_prompt, str) and f"${name}" not in default_prompt:
                    validation.error(openai_path, f"interface.default_prompt must mention ${name}")

        alias = codex_root / name
        expected_target = Path("../../.claude/skills") / name
        if not alias.is_symlink() and not alias.exists():
            validation.error(alias, "missing Codex alias for canonical Claude skill")
        elif not alias.is_symlink():
            validation.error(
                alias,
                "Codex repository skill alias must be a symlink; on Windows, enable Developer "
                "Mode and Git core.symlinks before cloning",
            )
        elif alias.readlink() != expected_target:
            validation.error(alias, f"Codex alias must target {expected_target.as_posix()}")

    aliases = {path.name: path for path in codex_root.iterdir()} if codex_root.is_dir() else {}
    for name, alias in sorted(aliases.items()):
        if name not in canonical:
            validation.error(alias, "Codex alias has no canonical Claude skill")


def validate_readme(skill_names: dict[str, set[str]], validation: Validation) -> None:
    path = ROOT / "README.md"
    body = path.read_text(encoding="utf-8")
    for plugin, names in skill_names.items():
        for name in names:
            if f"/{plugin}:{name}" not in body:
                validation.error(path, f"skill inventory is missing /{plugin}:{name}")
    if "codex plugin add compass@compass-marketplace" not in body:
        validation.error(path, "Codex installation must install compass")


def check_installed_runtime(plugin_root: Path) -> int:
    """Report the runtime inventory for one installed plugin copy.

    Exposed as a flag so CI can point it at an installed path without
    embedding a second copy of the inventory in YAML or shell.
    """
    validation = Validation()
    validate_runtime_files(plugin_root, validation)
    for error in validation.errors:
        print(f"::error::{error}")
    if validation.errors:
        return 1
    print(f"Runtime inventory complete: {len(COMPASS_RUNTIME_FILES)} files under {plugin_root}.")
    return 0


def main() -> int:
    if "--public-text" in sys.argv[1:]:
        if len(sys.argv) != 3 or sys.argv[1] != "--public-text":
            print("::error::usage: validate_plugins.py --public-text FILE")
            return 2
        return check_public_text(Path(sys.argv[2]))
    if len(sys.argv) == 3 and sys.argv[1] == "--runtime-files":
        return check_installed_runtime(Path(sys.argv[2]))
    validation = Validation()
    manifests: dict[str, dict[str, Any] | None] = {}
    gemini_manifests: dict[str, dict[str, Any] | None] = {}
    antigravity_manifests: dict[str, dict[str, Any] | None] = {}
    skill_names: dict[str, set[str]] = {}
    catalog_lines: list[str] = []
    for plugin_name in PLUGIN_NAMES:
        plugin_root = ROOT / plugin_name
        manifests[plugin_name] = validate_codex_manifest(plugin_root, validation)
        antigravity_manifests[plugin_name] = validate_antigravity_manifest(plugin_root, validation)
        gemini_root = ROOT / GEMINI_EXTENSION_ROOT
        gemini_manifests[plugin_name] = validate_gemini_extension(
            gemini_root, plugin_name, validation
        )
        droid_root = ROOT / DROID_EXTENSION_ROOT
        validate_droid_extension(droid_root, plugin_name, validation)
        mcp_config = validate_antigravity_mcp_config(plugin_root, validation)
        validate_mcp_endpoint_parity(
            gemini_root, gemini_manifests[plugin_name], mcp_config, validation
        )
        validate_hooks_adapter(plugin_root, validation)
        validate_hooks_adapter(gemini_root, validation)
        validate_hooks_adapter(droid_root, validation)
        validate_runtime_files(plugin_root, validation)
        skill_names[plugin_name], plugin_catalog_lines = validate_skills(plugin_root, validation)
        catalog_lines.extend(plugin_catalog_lines)
        legacy_commands = list((plugin_root / "commands").glob("*.md"))
        if legacy_commands:
            validation.error(
                plugin_root / "commands", "legacy commands must be migrated to shared skills"
            )

    validate_hook_vocabulary(validation)
    if shutil.which("node"):
        for problem in check_js_adapters(ROOT / "compass/skills/compass"):
            validation.error("JavaScript adapters", problem)
    else:
        print("warning: node not found — JavaScript adapter checks skipped; required by lint job")
    validate_antigravity_hook_nesting(validation)
    validate_duplicated_scripts(validation)
    validate_marketplaces(manifests, gemini_manifests, antigravity_manifests, validation)
    validate_readme(skill_names, validation)
    validate_repository_skills(validation)
    validate_repo_docs(validation)
    validate_public_docs(validation)
    validate_promise_parity(validation)

    catalog_text = "\n".join(catalog_lines) + "\n"
    catalog_token_estimate = approx_token_count(catalog_text)
    if catalog_token_estimate > MAX_CATALOG_TOKEN_ESTIMATE:
        validation.error(
            "skills",
            f"combined repository catalog estimate is {catalog_token_estimate} tokens; "
            f"repository maximum is {MAX_CATALOG_TOKEN_ESTIMATE}",
        )

    if validation.errors:
        print("Plugin compatibility validation failed:")
        for error in validation.errors:
            print(f"- {error}")
        return 1
    print(
        f"Validated {sum(map(len, skill_names.values()))} skills across "
        f"{len(PLUGIN_NAMES)} plugins "
        f"({catalog_token_estimate} repository-estimated catalog tokens, "
        f"{len(catalog_text)} rendered bytes)."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
