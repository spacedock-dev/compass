"""Reviewed primitive boundaries. AST checks are a review tripwire, not dataflow proof."""

from __future__ import annotations

import ast
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]


# Modules own the policy, rather than permitting every caller of an opener.
OPENERS = {
    "compass_runtime/https_transport.py": "Whole-exchange HTTPS deadline transport.",
    "compass_runtime/loopback_transport.py": "Proxy-free bounded loopback HTTP transport.",
    "compass_runtime/reach.py": "Opt-in HTTPS delivery, proxy-free and redirect-refusing.",
}

# module/qualified lexical owner -> (reviewed argv expressions, reason). Exact argv shapes also reject
# a bare binary planted in an already reviewed function; this is not interprocedural proof.
PROCESSES = {
    ("launch.py", "find_new_python"): (
        (
            "[uv, 'python', 'find', f'>={FLOOR[0]}.{FLOOR[1]}', '--no-python-downloads', '--no-project', '--no-config', '--system']",
        ),
        "uv comes from launch.lookup, the Python 3.6 copy of rooted lookup.",
    ),
    ("launch.py", "run_elsewhere"): (
        ("command",),
        "Caller supplies this interpreter or rooted lookup's interpreter.",
    ),
    ("compass_runtime/focus.py", "run_rooted"): (
        ("resolved",),
        "rooted_path.prepared resolves argv and scrubs child PATH.",
    ),
    ("compass_runtime/interaction_prototype.py", "TmuxAdapter.start_read_only_stream"): (
        (
            "[self._executable, '-f', '/dev/null', '-S', self._socket, '-CC', 'attach-session', '-r', '-t', origin.session_id]",
        ),
        "Constructor resolves tmux through rooted_path.which and validates rooted overrides.",
    ),
    ("compass_runtime/interaction_prototype.py", "TmuxAdapter._run"): (
        ("[self._executable, '-f', '/dev/null', '-S', self._socket, *arguments]",),
        "Same constructor-resolved tmux; child PATH is scrubbed.",
    ),
    ("compass_runtime/lifecycle.py", "spawn_detached"): (
        ("spawn_argv(config, args)",),
        "spawn_argv binds sys.executable, never a PATH binary.",
    ),
    ("compass_runtime/notifications.py", "notify_mac"): (
        ("['/usr/bin/osascript', '-e', script]",),
        "Fixed OS program: PATH lookup would weaken the absolute binding.",
    ),
    ("compass_runtime/supervise.py", "_group_running.read"): (
        ("['/bin/ps', '-axo', 'pgid=,stat=']",),
        "Fixed POSIX process table reader; no PATH lookup.",
    ),
    ("compass_runtime/plan/tracker_cli.py", "TrackerCLI._capture"): (
        ("[self._executable, *arguments]",),
        (
            "Rooted tracker CLI with adapter-owned argv, a supervised deadline and an output cap. "
            "Linear pins its workspace and uses issue query, milestone list and project view only."
        ),
    ),
    ("compass_runtime/supervise.py", "_spawn"): (
        ("command", "command"),
        "Group-containment primitive; callers resolve argv (review obligation).",
    ),
    ("compass_runtime/terminal_client.py", "start_daemon"): (
        ("argv",),
        "base_argv binds sys.executable or the frozen executable.",
    ),
    ("compass_runtime/terminal_monitor.py", "spawn"): (
        ("argv",),
        "This interpreter/frozen executable and installed launcher, no PATH search.",
    ),
    ("compass_runtime/terminal_monitor.py", "process_identity"): (
        ("['/bin/ps', '-ww', '-o', 'ppid=,lstart=,comm=', '-p', str(pid)]",),
        "Fixed OS process identity reader; no PATH search.",
    ),
}

# Injectable runners are launches too: a new default must not evade the direct-call scan.
RUNNERS = {
    (
        "compass_runtime/ci_read.py",
        "probe_session",
    ): "Git executable comes through git_status/rooted_path lookup.",
    (
        "compass_runtime/git_status.py",
        "probe",
    ): "Local git_status.executable delegates to rooted_path.which.",
    (
        "compass_runtime/git_status.py",
        "plan_reader",
    ): "Uses the rooted Git executable for fixed local-ref, object, blame and timestamp reads.",
    (
        "compass_runtime/git_status.py",
        "identity",
    ): "Local git_status.executable delegates to rooted_path.which.",
    (
        "compass_runtime/git_status.py",
        "is_ancestor",
    ): "Local git_status.executable delegates to rooted_path.which.",
    (
        "compass_runtime/git_status.py",
        "read_committed",
    ): "Local git_status.executable delegates to rooted_path.which.",
    (
        "compass_runtime/project_context.py",
        "discover_project_workflows",
    ): "Binary resolver defaults to rooted_path.which.",
    (
        "compass_runtime/project_context.py",
        "_project_workflow_discovery",
    ): "Forwards the rooted workflow-discovery runner.",
    (
        "compass_runtime/project_scripts.py",
        "load",
    ): "Committed-file reader resolves git through git_status.executable.",
    (
        "compass_runtime/quota.py",
        "fetch_usage",
    ): "Credential reader invokes fixed /usr/bin/security; no PATH search.",
    (
        "compass_runtime/quota.py",
        "request_fetch",
    ): "Forwards the fixed /usr/bin/security credential reader's runner.",
    (
        "compass_runtime/reading_source_collect.py",
        "collect",
    ): "Forwards the rooted Git probe runner.",
}

# Raw file calls are reviewed by module and qualified lexical owner, with call counts so adding a twin
# inside an existing function also fails. KNOWN GAP entries freeze debt, not certify safety.
RAW_FILES: dict[tuple[str, str], tuple[int, str]] = {
    ("launch.py", "main"): (
        1,
        "main: Script source explicitly requested by the invoking harness, executed as Python would; not state data.",
    ),
    ("notify_hook.py", "_open_state"): (
        1,
        "_open_state: Held parent, NOFOLLOW/NONBLOCK leaf, and _check_regular descriptor validation.",
    ),
    ("notify_hook.py", "_windows_directory"): (
        2,
        "_windows_directory: Configured root creation, then owned non-reparse descendants held by Windows handles.",
    ),
    ("notify_hook.py", "_directory_child"): (
        3,
        "_directory_child: Relative held-parent directory opens with NOFOLLOW; _directory_fd checks ownership and bounds trusted links.",
    ),
    ("notify_hook.py", "_directory_fd"): (
        1,
        "_directory_fd: Opens fixed filesystem root for the checked held-directory walk, no content read.",
    ),
    ("notify_hook.py", "_owner_directory_fd"): (
        3,
        "_owner_directory_fd: Confined descendants opened relative to held owned parents with NOFOLLOW and mode checks.",
    ),
    ("notify_hook.py", "write_owner_json"): (
        1,
        "write_owner_json: Exclusive owner-only staging leaf under checked held parents, then atomic replacement.",
    ),
    ("compass_runtime/annotations.py", "_fsync_directory"): (
        1,
        "_fsync_directory: Directory descriptor for durability, no content read.",
    ),
    ("compass_runtime/ci_read.py", "_run"): (
        2,
        "_run: Private TemporaryDirectory output captures for a bounded subprocess.",
    ),
    ("compass_runtime/claude_settings.py", "document"): (
        1,
        "document: External settings descriptor checked for regular file and bounded reads.",
    ),
    ("compass_runtime/frontend_dev.py", "load_manifest"): (
        1,
        "KNOWN GAP: Vite-authored development manifest, not Compass state; temporary directory read uses Path.open.",
    ),
    ("compass_runtime/git_status.py", "_read_regular"): (
        1,
        "_read_regular: Nonblocking descriptor with regular-file and size checks for repository data.",
    ),
    ("compass_runtime/http_api.py", "_RequestHandler._interaction_asset"): (
        2,
        "_RequestHandler._interaction_asset: Bundled terminal assets verified against shipped SHA-256 digests.",
    ),
    ("compass_runtime/https_transport.py", "open_bounded"): (
        1,
        "open_bounded: HTTP opener.open, not a filesystem operation.",
    ),
    ("compass_runtime/interaction_prototype.py", "_read_registration_generation"): (
        1,
        "_read_registration_generation: Registration helper validates descriptor identity and generation.",
    ),
    ("compass_runtime/interaction_prototype.py", "_read_registration_file"): (
        1,
        "_read_registration_file: Registration helper refuses links and nonregular files using descriptor checks.",
    ),
    ("compass_runtime/lifecycle.py", "_identity_text"): (
        1,
        "_identity_text: Fixed OS identity paths; nonblocking nofollow regular descriptor, root/user owner, 1024-byte cap.",
    ),
    ("compass_runtime/lifecycle.py", "daemon_redirect_stdio"): (
        1,
        "daemon_redirect_stdio: OS null device for detached process stdin.",
    ),
    ("compass_runtime/observer.py", "_state_reading_root"): (
        1,
        "_state_reading_root: mkdir under a canonical parent verified by _private_reading_parent; rejects links and verifies 0700 user ownership afterward without chmod.",
    ),
    ("compass_runtime/project_context.py", "frozen_codex_sources"): (
        2,
        "frozen_codex_sources: Exclusive owner-only copy inside a newly created private temporary directory.",
    ),
    ("compass_runtime/project_context.py", "frozen_codex_user_messages"): (
        1,
        "frozen_codex_user_messages: Reads its private frozen transcript copy.",
    ),
    ("compass_runtime/project_scripts.py", "_read_regular"): (
        1,
        "_read_regular: Descriptor helper checks regular-file identity and read cap.",
    ),
    ("compass_runtime/reach.py", "_stored_reach_url"): (
        1,
        "_stored_reach_url: NOFOLLOW, NONBLOCK and same-descriptor owner/mode/identity checks.",
    ),
    ("compass_runtime/reader_checks.py", "_read"): (
        1,
        "KNOWN GAP: reader-authored checks, never written by Compass; follows links and lacks owner/identity checks despite nonblocking regular-file reads.",
    ),
    ("compass_runtime/reading_ci_acquire.py", "_Read.ci"): (
        1,
        "_Read.ci: self.open opens an acquisition context, not a file.",
    ),
    ("compass_runtime/reading_ci_acquire.py", "_Read.git"): (
        1,
        "_Read.git: self.open opens an acquisition context, not a file.",
    ),
    ("compass_runtime/reading_ci_acquire.py", "_Read.read"): (
        1,
        "_Read.read: self.open opens an acquisition context, not a file.",
    ),
    ("compass_runtime/reading_long_markers.py", "sync_directory"): (
        1,
        "sync_directory: Directory durability descriptor, no file content.",
    ),
    ("compass_runtime/reading_policy.py", "_connect"): (
        1,
        "_connect: Owner-only SQLite placeholder descriptor with NOFOLLOW/NONBLOCK.",
    ),
    ("compass_runtime/reading_route.py", "_aws_config"): (
        1,
        "_aws_config: External AWS settings read through bounded descriptor checks.",
    ),
    ("compass_runtime/sessions.py", "_git_checkout"): (
        2,
        "_git_checkout: Repository gitdir/commondir marker reads, not Compass state.",
    ),
    ("compass_runtime/terminal_client.py", "read_line"): (
        1,
        "read_line: Nonblocking regular-file read helper for external harness status.",
    ),
    ("compass_runtime/terminal_client.py", "release_version"): (
        2,
        "release_version: Installed immutable version/manifest data.",
    ),
    ("compass_runtime/update_check.py", "_read"): (
        1,
        "_read: Nonblocking regular-file descriptor checked for cap and metadata.",
    ),
    ("compass_runtime/web/page.py", "_verified_file"): (
        1,
        "_verified_file: Bundled frontend assets with integrity verification.",
    ),
    ("compass_runtime/web/page.py", "_load_react_page"): (
        1,
        "_load_react_page: Bundled integrity metadata, not Compass state.",
    ),
}


# Installed copies have separate module keys, so drift in either copy is checked too.
for _harness in ("compass-gemini", "compass-droid"):
    PROCESSES.update(
        {
            (f"{_harness}/hooks/{module}", function): entry
            for (module, function), entry in list(PROCESSES.items())
            if module == "launch.py"
        }
    )
    RAW_FILES.update(
        {
            (f"{_harness}/hooks/{module}", function): entry
            for (module, function), entry in list(RAW_FILES.items())
            if module in {"launch.py", "notify_hook.py"}
        }
    )


# These inputs are authored outside Compass; no Compass-written state reader may claim a gap.
NON_STATE_READ_GAPS = frozenset(
    {
        ("compass_runtime/frontend_dev.py", "load_manifest"),
        ("compass_runtime/reader_checks.py", "_read"),
    }
)

# These calls admit settings and source bytes only through plan's validated declarations.
PLAN_FILE_CALLS: dict[tuple[str, str, str], tuple[int, str]] = {
    ("compass_runtime/plan/settings.py", "load", "read_plan_settings"): (
        1,
        "Reads the fixed Compass-home settings leaf through the checkout and link guards.",
    ),
    ("compass_runtime/plan/sources.py", "Sources._read", "read_plan_source"): (
        1,
        (
            "Reads the exact event log or a direct brief admitted by the filename grammar,"
            " with checked ancestors and a byte cap."
        ),
    ),
    ("compass_runtime/plan/sources.py", "Sources.brief_names", "list_plan_names"): (
        1,
        "Lists names only inside the declared, guarded brief folder under an entry cap.",
    ),
}
PLAN_FILE_PRIMITIVES = {name for _, _, name in PLAN_FILE_CALLS} | {"open_plan_source"}


def _name(node: ast.expr, imports: dict[str, str]) -> str:
    if isinstance(node, ast.Name):
        return imports.get(node.id, node.id)
    if isinstance(node, ast.Attribute):
        return _name(node.value, imports) + "." + node.attr
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "getattr"
        and len(node.args) >= 2
    ):
        attribute = node.args[1]
        suffix = (
            attribute.value
            if isinstance(attribute, ast.Constant) and isinstance(attribute.value, str)
            else "<dynamic>"
        )
        return _name(node.args[0], imports) + "." + suffix
    if isinstance(node, ast.BoolOp):
        # A fallback to a primitive is still a primitive site, even with an injected runner.
        for value in node.values:
            name = _name(value, imports)
            if _sensitive_name(name):
                return name
    return ast.unparse(node)


def _sensitive_name(name: str) -> bool:
    return (
        name in {"open", "compass_runtime.io"}
        or name.startswith("compass_runtime.io.")
        or name.split(".", maxsplit=1)[0]
        in {
            "subprocess",
            "urllib",
            "os",
            "io",
            "builtins",
            "pathlib",
            "asyncio",
            "pty",
        }
    )


def _process(name: str) -> bool:
    return name in {
        "subprocess.run",
        "subprocess.Popen",
        "subprocess.check_output",
        "subprocess.call",
        "subprocess.check_call",
        "subprocess.getoutput",
        "subprocess.getstatusoutput",
        "os.system",
        "os.popen",
        "pty.spawn",
        "asyncio.create_subprocess_exec",
        "asyncio.create_subprocess_shell",
    } or name.startswith(("os.exec", "os.spawn", "os.posix_spawn"))


def _import_base(node: ast.ImportFrom, module: str) -> str:
    """Absolute dotted module of a from-import; a relative level is read against the file's package."""
    if node.level == 0:
        return node.module or ""
    package = module.removesuffix(".py").split("/")[:-1]
    if node.level - 1 > len(package):
        return ""
    base = package[: len(package) - (node.level - 1)]
    return ".".join([*base, *([node.module] if node.module else [])])


def _imports(tree: ast.AST, module: str) -> dict[str, str]:
    found = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                found[alias.asname or alias.name.split(".")[0]] = (
                    alias.name if alias.asname else alias.name.split(".")[0]
                )
        elif isinstance(node, ast.ImportFrom) and (base := _import_base(node, module)):
            for alias in node.names:
                found[alias.asname or alias.name] = base + "." + alias.name
    return _assigned_aliases(tree, found)


def _assigned_aliases(tree: ast.AST, found: dict[str, str]) -> dict[str, str]:
    assignments = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Assign) or (isinstance(node, ast.AnnAssign) and node.value)
    ]
    # Bound the lexical fixed point by the number of assignments; no execution or inference.
    for _ in assignments:
        previous = found.copy()
        for node in assignments:
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                if isinstance(target, ast.Name) and node.value is not None:
                    resolved = _name(node.value, found)
                    if _sensitive_name(resolved):
                        found[target.id] = resolved
        if found == previous:
            break
    return found


def _owner(node: ast.AST, parents: dict[ast.AST, ast.AST]) -> str:
    names = []
    while True:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.append(node.name)
        if node not in parents:
            break
        node = parents[node]
    return ".".join(reversed(names)) or "<module>"


def _runner_defaults(
    tree: ast.AST, imports: dict[str, str], module: str, parents: dict[ast.AST, ast.AST]
) -> list[str]:
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        defaults = [*node.args.defaults, *node.args.kw_defaults]
        runners = [
            value for value in defaults if value is not None and _process(_name(value, imports))
        ]
        function = _owner(node, parents)
        if runners and ((module, function) not in RUNNERS or len(runners) != 1):
            found.append(f"{module} {function}: unreviewed injectable process runner")
    return found


def violations(source: str, module: str) -> list[str]:
    tree = ast.parse(source)
    imports = _imports(tree, module)
    parents = {child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}
    found = _runner_defaults(tree, imports, module, parents)
    counts: dict[tuple[str, str], int] = {}
    process_counts: dict[tuple[str, str], int] = {}
    plan_counts: dict[tuple[str, str, str], int] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        function = _owner(node, parents)
        key = module, function
        name = _name(node.func, imports)
        prefix = f"{module}:{node.lineno} {function}: "
        plan_primitive = name.removeprefix("compass_runtime.io.")
        if name.startswith("compass_runtime.io.") and plan_primitive in PLAN_FILE_PRIMITIVES:
            found.extend(_count_plan_call(plan_counts, (*key, plan_primitive), prefix))
        resolved = _name(node, imports)
        if any(
            value.endswith(".<dynamic>") and _sensitive_name(value) for value in (name, resolved)
        ):
            found.append(prefix + "unresolved primitive attribute requires review")
        if (
            name in {"urllib.request.urlopen", "urllib.request.build_opener"}
            and module not in OPENERS
        ):
            found.append(prefix + "unreviewed HTTP opener")
        if _process(name) or name == "compass_runtime.supervise.run":
            allowed, _reason = PROCESSES.get(key, ((), ""))
            argv = ast.unparse(node.args[0]) if node.args else ""
            process_counts[key] = process_counts.get(key, 0) + 1
            if argv not in allowed or process_counts[key] > len(allowed):
                found.append(prefix + "unreviewed process executable")
        raw = name in {
            "open",
            "builtins.open",
            "io.open",
            "os.open",
            "os.makedirs",
            "os.mkdir",
        } or name.endswith(
            (".open", ".read_bytes", ".read_text", ".write_bytes", ".write_text", ".mkdir")
        )
        if module not in {"compass_runtime/io.py", "compass_runtime/spacedock.py"} and raw:
            counts[key] = counts.get(key, 0) + 1
            maximum, _reason = RAW_FILES.get(key, (0, ""))
            if counts[key] > maximum:
                found.append(prefix + "unreviewed raw file operation")
    found.extend(_stale_entries(module, counts, process_counts, plan_counts))
    return found


def _stale_entries(
    module: str,
    counts: dict[tuple[str, str], int],
    process_counts: dict[tuple[str, str], int],
    plan_counts: dict[tuple[str, str, str], int],
) -> list[str]:
    found = []
    for key, (maximum, reason) in RAW_FILES.items():
        if key[0] == module and reason.startswith("KNOWN GAP") and key not in NON_STATE_READ_GAPS:
            found.append(f"{module} {key[1]}: unreviewed Compass-written state-read gap")
        if key[0] == module and counts.get(key, 0) < maximum:
            found.append(f"{module} {key[1]}: stale raw-file inventory")
    for key, (arguments, _reason) in PROCESSES.items():
        if key[0] == module and process_counts.get(key, 0) < len(arguments):
            found.append(f"{module} {key[1]}: stale process inventory")
    for plan_key, (maximum, _reason) in PLAN_FILE_CALLS.items():
        if plan_key[0] == module and plan_counts.get(plan_key, 0) < maximum:
            found.append(f"{module} {plan_key[1]} ({plan_key[2]}): stale plan-file inventory")
    return found


def _count_plan_call(
    plan_counts: dict[tuple[str, str, str], int], plan_key: tuple[str, str, str], prefix: str
) -> list[str]:
    plan_counts[plan_key] = plan_counts.get(plan_key, 0) + 1
    if plan_counts[plan_key] > PLAN_FILE_CALLS.get(plan_key, (0, ""))[0]:
        return [prefix + "unreviewed plan file operation"]
    return []


def _unscanned_plan_entries(scanned: set[str]) -> list[str]:
    """Plan entries whose module was never scanned, so no per-module stale check could run."""
    return [
        f"{module} {owner} ({primitive}): stale plan-file inventory, module not scanned"
        for module, owner, primitive in PLAN_FILE_CALLS
        if module not in scanned
    ]


class SecurityPrimitivesTest(unittest.TestCase):
    def test_plan_primitive_requires_a_reviewed_caller(self) -> None:
        found = violations(
            "from compass_runtime import io; io.read_plan_source('/tmp/value', policy, 7)",
            "compass_runtime/new.py",
        )
        self.assertTrue(any("unreviewed plan file operation" in error for error in found))

    def test_a_relative_import_of_a_plan_primitive_requires_review(self) -> None:
        for source, module in (
            (
                "from .. import io; io.read_plan_source('/p', policy, 7)",
                "compass_runtime/plan/new.py",
            ),
            (
                "from ..io import read_plan_source as r; r('/p', policy, 7)",
                "compass_runtime/plan/new.py",
            ),
            ("from . import io; io.open_plan_source('/p', policy, 7)", "compass_runtime/new.py"),
        ):
            with self.subTest(source=source):
                found = violations(source, module)
                self.assertTrue(any("unreviewed plan file operation" in e for e in found), found)

    def test_an_assigned_alias_of_a_plan_primitive_requires_review(self) -> None:
        for source in (
            "from compass_runtime import io\nfn = io.read_plan_source\nfn('/p', policy, 7)",
            "from compass_runtime import io\nmod = io\nfn = mod.list_plan_names\nfn('/p', 1)",
            "from .. import io\nfn: object = getattr(io, 'read_plan_source')\nfn('/p', policy, 7)",
            "from compass_runtime import io\ndef f(cb=None):\n fn = cb or io.read_plan_source\n fn('/p', policy, 7)",
        ):
            with self.subTest(source=source):
                found = violations(source, "compass_runtime/plan/new.py")
                self.assertTrue(any("unreviewed plan file operation" in e for e in found), found)
        found = violations(
            "from .. import io\ndef f(m): return getattr(io, m)('/p')",
            "compass_runtime/plan/new.py",
        )
        self.assertTrue(any("unresolved primitive attribute" in e for e in found), found)

    def test_a_second_plan_call_from_a_reviewed_owner_requires_review(self) -> None:
        source = (
            "from compass_runtime import io\n"
            "def load():\n io.read_plan_settings('/a', 1)\n io.read_plan_settings('/b', 1)"
        )
        found = violations(source, "compass_runtime/plan/settings.py")
        self.assertTrue(any("load: unreviewed plan file operation" in e for e in found), found)
        self.assertFalse(any("stale" in e for e in found), found)

    def test_a_stale_plan_inventory_entry_is_refused(self) -> None:
        found = violations("def load():\n return None", "compass_runtime/plan/settings.py")
        self.assertTrue(any("stale plan-file inventory" in e for e in found), found)

    def test_a_plan_entry_for_a_missing_module_is_refused(self) -> None:
        key = ("compass_runtime/plan/missing.py", "load", "read_plan_settings")
        with mock.patch.dict(PLAN_FILE_CALLS, {key: (1, "stale")}):
            found = _unscanned_plan_entries(set())
        self.assertTrue(any("stale plan-file inventory" in e for e in found), found)

    def test_a_raw_open_in_any_shipped_top_level_script_requires_review(self) -> None:
        modules = [
            "notify_hook.py",
            "event_hook.py",
            "plan_summary_hook.py",
            "mcp_server.py",
            "statusline_hook.py",
            "agy_hook.py",
            "launch.py",
            "server.py",
            "compass-gemini/hooks/event_hook.py",
            "compass-gemini/hooks/notify_hook.py",
            "compass-gemini/hooks/launch.py",
            "compass-droid/hooks/event_hook.py",
            "compass-droid/hooks/notify_hook.py",
            "compass-droid/hooks/launch.py",
        ]
        for module in modules:
            with self.subTest(module=module):
                self.assertTrue(
                    any(
                        "unreviewed raw file operation" in error
                        for error in violations("open('/tmp/unreviewed')", module)
                    )
                )

    def test_same_named_methods_cannot_share_a_reviewed_primitive_entry(self) -> None:
        source = "class Other:\n def _run(self):\n  open('/tmp/unreviewed')"
        found = violations(source, "compass_runtime/ci_read.py")
        self.assertTrue(
            any("Other._run: unreviewed raw file operation" in error for error in found)
        )
        source = "import subprocess\nclass Other:\n def _run(self):\n  subprocess.run([self._executable, '-f', '/dev/null', '-S', self._socket, *arguments])"
        found = violations(source, "compass_runtime/interaction_prototype.py")
        self.assertTrue(
            any("Other._run: unreviewed process executable" in error for error in found)
        )
        source = "import subprocess\nclass Other:\n def probe(self, runner=subprocess.run): pass"
        found = violations(source, "compass_runtime/git_status.py")
        self.assertTrue(
            any("Other.probe: unreviewed injectable process runner" in error for error in found)
        )

    def test_static_alias_default_and_launcher_bypasses_rejected(self) -> None:
        for source in (
            "import urllib.request; req = urllib.request; req.urlopen('u')",
            "import subprocess; s = subprocess; s.run(['git'])",
            "fn = open; fn('/tmp/x')",
            "import io; fn = io.open; fn('/tmp/x')",
            "import builtins; fn = builtins.open; fn('/tmp/x')",
            "from pathlib import Path; fn = Path.open; fn(Path('/tmp/x'))",
            "import subprocess; getattr(subprocess, 'run')(['git'])",
            "import urllib.request; getattr(urllib.request, 'urlopen')('u')",
            "import builtins; getattr(builtins, 'open')('/tmp/x')",
            "import os; os.popen('id')",
            "import os; os.system('id')",
            "import asyncio; asyncio.create_subprocess_exec('git')",
            "import asyncio; asyncio.create_subprocess_shell('id')",
            "import subprocess; subprocess.getoutput('id')",
            "import subprocess\ndef f(runner=subprocess.call):\n runner(['git'])",
            "import subprocess\ndef f(runner=None):\n fn = runner or subprocess.run\n fn(['git'])",
            "import os; os.posix_spawn('git', ['git'], {})",
            "import os; os.execlp('git', 'git')",
            "import pty; pty.spawn(['git'])",
            "import subprocess\ndef f(method):\n getattr(subprocess, method)(['git'])",
            "import subprocess\ndef f(method):\n launch = getattr(subprocess, method)\n launch(['git'])",
            "import subprocess\ndef f(method):\n return getattr(subprocess, method)",
            "import subprocess\ndef f(runner=getattr(subprocess, method)):\n runner(['git'])",
        ):
            with self.subTest(source=source):
                self.assertTrue(violations(source, "compass_runtime/new.py"))

    def test_deferred_unsafe_sites_remain_known_gaps(self) -> None:
        missing = {
            ("compass_runtime/reader_checks.py", "_read"): ("owner", "link"),
        }
        for key, gaps in missing.items():
            with self.subTest(key=key):
                description = RAW_FILES[key][1]
                self.assertTrue(description.startswith("KNOWN GAP:"))
                for gap in gaps:
                    self.assertIn(gap, description.lower())
        # Naming the reviewed function keeps generic claims of full protection out of entries.
        for (_module, function), (_count, reason) in RAW_FILES.items():
            if not reason.startswith("KNOWN GAP:"):
                with self.subTest(function=function):
                    self.assertIn(function, reason)

    def test_production_tree_uses_reviewed_primitives(self) -> None:
        found = []
        scanned: set[str] = set()
        for path in sorted(ROOT.rglob("*.py")):
            if "tests" not in path.relative_to(ROOT).parts:
                scanned.add(path.relative_to(ROOT).as_posix())
                found.extend(
                    violations(path.read_text(encoding="utf-8"), path.relative_to(ROOT).as_posix())
                )
        repository = ROOT.parents[2]
        for harness in ("compass-gemini", "compass-droid"):
            for path in sorted((repository / harness / "hooks").glob("*.py")):
                found.extend(
                    violations(
                        path.read_text(encoding="utf-8"), path.relative_to(repository).as_posix()
                    )
                )
        found.extend(_unscanned_plan_entries(scanned))
        self.assertEqual([], found, "\n".join(found))

    def test_new_openers_are_refused_even_through_import_aliases(self) -> None:
        for source in (
            "import urllib.request; urllib.request.urlopen('https://example.com')",
            "from urllib.request import build_opener as make; make()",
            "import urllib.request as req; req.urlopen('u')",
            "import urllib.request; fetch = urllib.request.urlopen; fetch('u')",
        ):
            with self.subTest(source=source):
                self.assertTrue(violations(source, "compass_runtime/new.py"))

    def test_new_process_sites_and_bare_binaries_in_reviewed_functions_are_refused(self) -> None:
        for source, module in (
            ("import subprocess; subprocess.run(['git'])", "compass_runtime/new.py"),
            ("from subprocess import Popen as start; start(['git'])", "new.py"),
            ("import os; os.execvp('git', ['git'])", "new.py"),
            ("import os; os.spawnlp(0, 'git', 'git')", "new.py"),
            (
                "import subprocess\ndef run_rooted(argv):\n subprocess.run(['tmux'])",
                "compass_runtime/focus.py",
            ),
        ):
            with self.subTest(source=source):
                self.assertTrue(violations(source, module))

    def test_a_state_reader_cannot_be_exempted_by_adding_a_known_gap(self) -> None:
        source = "def load():\n return open('/state/compass-settings.json').read()"
        for module in ("compass_runtime/settings.py", "compass_runtime/future_state.py"):
            with (
                self.subTest(module=module),
                mock.patch.dict(RAW_FILES, {(module, "load"): (1, "KNOWN GAP: state read.")}),
            ):
                self.assertTrue(
                    any("state-read gap" in reason for reason in violations(source, module))
                )

    def test_new_raw_file_sites_are_refused(self) -> None:
        for call in (
            "open('/tmp/compass', 'rb')",
            "Path('/tmp/compass').open('rb')",
            "Path('/tmp/compass').read_bytes()",
            "Path('/tmp/compass').read_text()",
            "Path('/tmp/compass').write_text('data')",
            "Path('/tmp/compass').write_bytes(b'data')",
            "os.makedirs('/tmp/compass', exist_ok=True)",
            "Path('/tmp/compass').mkdir(exist_ok=True)",
            "os.open('/tmp/compass', 0)",
        ):
            with self.subTest(call=call):
                self.assertTrue(
                    violations(
                        "from pathlib import Path\nimport os\n" + call, "compass_runtime/new.py"
                    )
                )

    def test_an_unreviewed_supervised_tracker_launch_is_refused(self) -> None:
        source = "from compass_runtime import supervise\ndef launch():\n supervise.run(['gh'])"
        found = violations(source, "compass_runtime/plan/tracker_cli.py")
        self.assertTrue(any("unreviewed process executable" in item for item in found), found)

    def test_a_new_injected_subprocess_default_also_requires_review(self) -> None:
        source = "import subprocess\ndef run(runner=subprocess.run):\n runner(['git'])"
        self.assertTrue(violations(source, "compass_runtime/new.py"))

    def test_another_raw_read_in_a_reviewed_function_requires_review(self) -> None:
        source = "def load():\n open('/tmp/a')\n open('/tmp/b')"
        self.assertTrue(violations(source, "compass_runtime/ends.py"))

    def test_comments_and_non_file_reads_are_not_calls(self) -> None:
        self.assertEqual(
            [], violations("# open('/tmp/x')\nvalue = stream.read()", "compass_runtime/new.py")
        )
