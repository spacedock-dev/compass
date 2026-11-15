"""Reviewed primitive boundaries. AST checks are a review tripwire, not dataflow proof."""

from __future__ import annotations

import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


# Modules own the policy, rather than permitting every caller of an opener.
OPENERS = {
    "compass_runtime/https_transport.py": "Whole-exchange HTTPS deadline transport.",
    "compass_runtime/loopback_transport.py": "Proxy-free bounded loopback HTTP transport.",
    "compass_runtime/reach.py": "Opt-in HTTPS delivery, proxy-free and redirect-refusing.",
}

# module/function -> (reviewed argv expressions, reason). Exact argv shapes also reject
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
    ("compass_runtime/interaction_prototype.py", "start_read_only_stream"): (
        (
            "[self._executable, '-f', '/dev/null', '-S', self._socket, '-CC', 'attach-session', '-r', '-t', origin.session_id]",
        ),
        "Constructor resolves tmux through rooted_path.which and validates rooted overrides.",
    ),
    ("compass_runtime/interaction_prototype.py", "_run"): (
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
    ("compass_runtime/supervise.py", "read"): (
        ("['/bin/ps', '-axo', 'pgid=,stat=']",),
        "Fixed POSIX process table reader; no PATH lookup.",
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

# Raw file calls are reviewed by module and function, with call counts so adding a twin
# inside an existing function also fails. KNOWN GAP entries freeze debt, not certify safety.
RAW_FILES: dict[tuple[str, str], tuple[int, str]] = {
    ("compass_runtime/annotations.py", "_fsync_directory"): (
        1,
        "Directory descriptor for durability, no content read.",
    ),
    ("compass_runtime/annotations.py", "_read_store"): (
        1,
        "KNOWN GAP: Compass annotation state uses blocking, symlink-following open.",
    ),
    ("compass_runtime/ci_read.py", "_run"): (
        2,
        "Private TemporaryDirectory output captures for a bounded subprocess.",
    ),
    ("compass_runtime/claude_data.py", "_advance_prompts"): (
        1,
        "External harness transcript, not Compass state.",
    ),
    ("compass_runtime/claude_data.py", "session_title"): (
        1,
        "External harness transcript, not Compass state.",
    ),
    ("compass_runtime/claude_data.py", "session_goal"): (
        1,
        "External harness transcript, not Compass state.",
    ),
    ("compass_runtime/claude_settings.py", "document"): (
        1,
        "External settings descriptor checked for regular file and bounded reads.",
    ),
    ("compass_runtime/collectors/antigravity.py", "_session_metadata"): (
        1,
        "External harness metadata, not Compass state.",
    ),
    ("compass_runtime/collectors/claude.py", "agent_label"): (
        1,
        "External harness agent metadata.",
    ),
    ("compass_runtime/collectors/claude.py", "load_team_members"): (
        1,
        "External harness team metadata.",
    ),
    ("compass_runtime/collectors/claude.py", "load_tasks"): (1, "External harness task metadata."),
    ("compass_runtime/collectors/pi.py", "_complete_end"): (1, "External Pi transcript."),
    ("compass_runtime/collectors/pi.py", "scan_pi_session"): (1, "External Pi transcript."),
    ("compass_runtime/compass_turns.py", "_advance"): (1, "External transcript cursor scanning."),
    ("compass_runtime/config.py", "load_pi_settings"): (1, "External Pi settings."),
    ("compass_runtime/copied_corrections.py", "_scan"): (
        1,
        "External transcript evidence scanning.",
    ),
    ("compass_runtime/copied_corrections.py", "_read"): (
        1,
        "KNOWN GAP: Compass state/marker raw read can follow links or block on a special file.",
    ),
    ("compass_runtime/deliveries.py", "load"): (
        1,
        "KNOWN GAP: Compass state/marker raw read can follow links or block on a special file.",
    ),
    ("compass_runtime/departures.py", "_load_at"): (
        1,
        "KNOWN GAP: Compass state/marker raw read can follow links or block on a special file.",
    ),
    ("compass_runtime/dismissals.py", "load"): (
        1,
        "KNOWN GAP: Compass state/marker raw read can follow links or block on a special file.",
    ),
    ("compass_runtime/ends.py", "load"): (
        1,
        "KNOWN GAP: Compass state/marker raw read can follow links or block on a special file.",
    ),
    ("compass_runtime/entry_numbers.py", "extend"): (1, "External transcript evidence scanning."),
    ("compass_runtime/frontend_dev.py", "load_manifest"): (
        1,
        "KNOWN GAP: development manifest under temporary directory uses Path.open.",
    ),
    ("compass_runtime/git_status.py", "_read_regular"): (
        1,
        "Nonblocking descriptor with regular-file and size checks for repository data.",
    ),
    ("compass_runtime/history.py", "load"): (
        1,
        "KNOWN GAP: Compass state/marker raw read can follow links or block on a special file.",
    ),
    ("compass_runtime/http_api.py", "_interaction_asset"): (
        2,
        "Bundled terminal assets verified against shipped SHA-256 digests.",
    ),
    ("compass_runtime/https_transport.py", "open_bounded"): (
        1,
        "HTTP opener.open, not a filesystem operation.",
    ),
    ("compass_runtime/interaction_prototype.py", "_read_registration_generation"): (
        1,
        "Registration helper validates descriptor identity and generation.",
    ),
    ("compass_runtime/interaction_prototype.py", "_read_registration_file"): (
        1,
        "Registration helper refuses links and nonregular files using descriptor checks.",
    ),
    ("compass_runtime/interaction_prototype.py", "start_client"): (
        1,
        "Exclusive owner-only temporary file in a private temporary directory.",
    ),
    ("compass_runtime/interaction_prototype.py", "_write_registration_file"): (
        2,
        "Registration helper uses exclusive owner-only staging and private directory checks.",
    ),
    ("compass_runtime/lifecycle.py", "daemon_redirect_stdio"): (
        1,
        "OS null device for detached process stdin.",
    ),
    ("compass_runtime/monitor_store.py", "lock"): (
        1,
        "Private lock helper with NOFOLLOW, NONBLOCK and descriptor identity checks.",
    ),
    ("compass_runtime/monitor_store.py", "read"): (
        1,
        "Private control-record helper with NOFOLLOW, NONBLOCK and identity checks.",
    ),
    ("compass_runtime/notifications.py", "resolve_quiet_hours"): (
        1,
        "KNOWN GAP: Compass state/marker raw read can follow links or block on a special file.",
    ),
    ("compass_runtime/observer.py", "read_sidecar"): (
        1,
        "KNOWN GAP: Compass state/marker raw read can follow links or block on a special file.",
    ),
    ("compass_runtime/project_context.py", "codex_source_prefix"): (
        1,
        "External harness transcript.",
    ),
    ("compass_runtime/project_context.py", "codex_activity_between"): (
        1,
        "External harness transcript.",
    ),
    ("compass_runtime/project_context.py", "codex_newest_final_words"): (
        1,
        "External harness transcript.",
    ),
    ("compass_runtime/project_context.py", "frozen_claude_user_messages"): (
        1,
        "External harness transcript.",
    ),
    ("compass_runtime/project_context.py", "frozen_claude_agent_messages"): (
        1,
        "External harness transcript.",
    ),
    ("compass_runtime/project_context.py", "claude_activity_between"): (
        1,
        "External harness transcript.",
    ),
    ("compass_runtime/project_context.py", "frozen_codex_sources"): (
        2,
        "Exclusive owner-only copy inside a newly created private temporary directory.",
    ),
    ("compass_runtime/project_context.py", "_frozen_codex_messages"): (
        1,
        "Reads its private frozen transcript copy.",
    ),
    ("compass_runtime/project_scripts.py", "_read_regular"): (
        1,
        "Descriptor helper checks regular-file identity and read cap.",
    ),
    ("compass_runtime/reach.py", "_stored_reach_url"): (
        1,
        "NOFOLLOW, NONBLOCK and same-descriptor owner/mode/identity checks.",
    ),
    ("compass_runtime/reach.py", "send_reach_nudge"): (
        1,
        "HTTP opener.open, not a filesystem operation.",
    ),
    ("compass_runtime/reader_checks.py", "_read"): (
        1,
        "Owner-only regular-file descriptor helper.",
    ),
    ("compass_runtime/reading_ci_acquire.py", "ci"): (
        1,
        "self.open opens an acquisition context, not a file.",
    ),
    ("compass_runtime/reading_ci_acquire.py", "git"): (
        1,
        "self.open opens an acquisition context, not a file.",
    ),
    ("compass_runtime/reading_ci_acquire.py", "read"): (
        1,
        "self.open opens an acquisition context, not a file.",
    ),
    ("compass_runtime/reading_jobs.py", "_mark_unstored"): (
        1,
        "KNOWN GAP: Compass state/marker raw read can follow links or block on a special file.",
    ),
    ("compass_runtime/reading_jobs.py", "cancel"): (
        1,
        "KNOWN GAP: Compass state/marker raw read can follow links or block on a special file.",
    ),
    ("compass_runtime/reading_jobs.py", "_recover"): (
        1,
        "KNOWN GAP: Compass state/marker raw read can follow links or block on a special file.",
    ),
    ("compass_runtime/reading_jobs.py", "_holder"): (
        1,
        "KNOWN GAP: Compass state/marker raw read can follow links or block on a special file.",
    ),
    ("compass_runtime/reading_long_markers.py", "_write"): (
        1,
        "Exclusive owner-only temporary staging descriptor.",
    ),
    ("compass_runtime/reading_long_markers.py", "sync_directory"): (
        1,
        "Directory durability descriptor, no file content.",
    ),
    ("compass_runtime/reading_long_markers.py", "_read"): (
        1,
        "KNOWN GAP: long-reading marker uses Path.open after path checks.",
    ),
    ("compass_runtime/reading_policy.py", "_connect"): (
        1,
        "Owner-only SQLite placeholder descriptor with NOFOLLOW/NONBLOCK.",
    ),
    ("compass_runtime/reading_route.py", "_aws_config"): (
        1,
        "External AWS settings read through bounded descriptor checks.",
    ),
    ("compass_runtime/record_pages.py", "scan_source"): (1, "External harness transcript."),
    ("compass_runtime/record_pages.py", "read"): (1, "External harness transcript."),
    ("compass_runtime/semantic_history.py", "_read"): (
        1,
        "KNOWN GAP: Compass state/marker raw read can follow links or block on a special file.",
    ),
    ("compass_runtime/sessions.py", "_git_checkout"): (
        2,
        "Repository gitdir/commondir marker reads, not Compass state.",
    ),
    ("compass_runtime/settings.py", "_read_store"): (
        1,
        "Owner-only settings helper with nonblocking descriptor checks.",
    ),
    ("compass_runtime/summary_jobs.py", "_eligible"): (
        1,
        "KNOWN GAP: Compass state/marker raw read can follow links or block on a special file.",
    ),
    ("compass_runtime/summary_jobs.py", "_stop"): (
        1,
        "KNOWN GAP: Compass state/marker raw read can follow links or block on a special file.",
    ),
    ("compass_runtime/summary_jobs.py", "cancel"): (
        1,
        "KNOWN GAP: Compass state/marker raw read can follow links or block on a special file.",
    ),
    ("compass_runtime/summary_jobs.py", "recover"): (
        1,
        "KNOWN GAP: Compass state/marker raw read can follow links or block on a special file.",
    ),
    ("compass_runtime/summary_store.py", "load"): (
        1,
        "KNOWN GAP: Compass state/marker raw read can follow links or block on a special file.",
    ),
    ("compass_runtime/terminal_client.py", "read_line"): (
        1,
        "Nonblocking regular-file read helper for external harness status.",
    ),
    ("compass_runtime/terminal_client.py", "release_version"): (
        2,
        "Installed immutable version/manifest data.",
    ),
    ("compass_runtime/transcripts.py", "first_prompt"): (1, "External harness transcript."),
    ("compass_runtime/tripwires.py", "load"): (
        1,
        "KNOWN GAP: Compass state/marker raw read can follow links or block on a special file.",
    ),
    ("compass_runtime/turns.py", "scan_turns"): (1, "External harness transcript."),
    ("compass_runtime/typed_press.py", "_consumed"): (
        1,
        "KNOWN GAP: Compass state/marker raw read can follow links or block on a special file.",
    ),
    ("compass_runtime/typed_press.py", "tail_lines"): (1, "External harness transcript."),
    ("compass_runtime/update_check.py", "_read"): (
        1,
        "Nonblocking regular-file descriptor checked for cap and metadata.",
    ),
    ("compass_runtime/web/page.py", "_verified_file"): (
        1,
        "Bundled frontend assets with integrity verification.",
    ),
    ("compass_runtime/web/page.py", "_load_react_page"): (
        1,
        "Bundled integrity metadata, not Compass state.",
    ),
}


def _name(node: ast.expr, imports: dict[str, str]) -> str:
    if isinstance(node, ast.Name):
        return imports.get(node.id, node.id)
    if isinstance(node, ast.Attribute):
        return _name(node.value, imports) + "." + node.attr
    return ast.unparse(node)


def _imports(tree: ast.AST) -> dict[str, str]:
    found = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                found[alias.asname or alias.name.split(".")[0]] = (
                    alias.name if alias.asname else alias.name.split(".")[0]
                )
        elif isinstance(node, ast.ImportFrom) and node.module:
            for alias in node.names:
                found[alias.asname or alias.name] = node.module + "." + alias.name
    return _assigned_aliases(tree, found)


def _assigned_aliases(tree: ast.AST, found: dict[str, str]) -> dict[str, str]:
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    resolved = _name(node.value, found)
                    if resolved.startswith(("subprocess.", "urllib.request.", "os.")):
                        found[target.id] = resolved
    return found


def _runner_defaults(tree: ast.AST, imports: dict[str, str], module: str) -> list[str]:
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        defaults = [*node.args.defaults, *node.args.kw_defaults]
        runners = [
            value
            for value in defaults
            if value is not None
            and _name(value, imports)
            in {"subprocess.run", "subprocess.Popen", "subprocess.check_output"}
        ]
        if runners and ((module, node.name) not in RUNNERS or len(runners) != 1):
            found.append(f"{module} {node.name}: unreviewed injectable process runner")
    return found


def violations(source: str, module: str) -> list[str]:
    tree = ast.parse(source)
    imports = _imports(tree)
    parents = {child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}
    found = _runner_defaults(tree, imports, module)
    counts: dict[tuple[str, str], int] = {}
    process_counts: dict[tuple[str, str], int] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        owner: ast.AST = node
        while owner in parents and not isinstance(owner, (ast.FunctionDef, ast.AsyncFunctionDef)):
            owner = parents[owner]
        function = getattr(owner, "name", "<module>")
        key = module, function
        name = _name(node.func, imports)
        prefix = f"{module}:{node.lineno} {function}: "
        if (
            name in {"urllib.request.urlopen", "urllib.request.build_opener"}
            and module not in OPENERS
        ):
            found.append(prefix + "unreviewed HTTP opener")
        if name in {
            "subprocess.run",
            "subprocess.Popen",
            "subprocess.check_output",
            "subprocess.call",
            "subprocess.check_call",
        } or name.startswith(("os.exec", "os.spawn", "os.posix_spawn")):
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
        if (
            module.startswith("compass_runtime/")
            and module not in {"compass_runtime/io.py", "compass_runtime/spacedock.py"}
            and raw
        ):
            counts[key] = counts.get(key, 0) + 1
            maximum, _reason = RAW_FILES.get(key, (0, ""))
            if counts[key] > maximum:
                found.append(prefix + "unreviewed raw file operation")
    found.extend(_stale_entries(module, counts, process_counts))
    return found


def _stale_entries(
    module: str, counts: dict[tuple[str, str], int], process_counts: dict[tuple[str, str], int]
) -> list[str]:
    found = []
    for key, (maximum, _reason) in RAW_FILES.items():
        if key[0] == module and counts.get(key, 0) < maximum:
            found.append(f"{module} {key[1]}: stale raw-file inventory")
    for key, (arguments, _reason) in PROCESSES.items():
        if key[0] == module and process_counts.get(key, 0) < len(arguments):
            found.append(f"{module} {key[1]}: stale process inventory")
    return found


class SecurityPrimitivesTest(unittest.TestCase):
    def test_production_tree_uses_reviewed_primitives(self) -> None:
        found = []
        for path in sorted(ROOT.rglob("*.py")):
            if "tests" not in path.relative_to(ROOT).parts:
                found.extend(
                    violations(path.read_text(encoding="utf-8"), path.relative_to(ROOT).as_posix())
                )
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
