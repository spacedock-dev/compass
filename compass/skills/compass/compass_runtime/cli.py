"""Argument parsing, runtime assembly, and the three serve branches."""

from __future__ import annotations

import argparse
import contextlib
import dataclasses
import ipaddress
import json
import math
import os
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING

from compass_runtime import (
    aggregate,
    copied_corrections,
    deliveries,
    diagnostics,
    ends,
    frontend_dev,
    history,
    http_api,
    lifecycle,
    notifications,
    observation,
    observer,
    reading_policy,
    summary_store,
    unasked,
)
from compass_runtime import annotations as annotation_store
from compass_runtime import config as runtime_config
from compass_runtime import interaction_prototype as runtime_interaction
from compass_runtime import io as runtime_io
from compass_runtime import state as runtime_state
from compass_runtime.web import page as frontend_page

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from compass_runtime.config import RuntimeConfig
    from compass_runtime.state import RuntimeState

DESCRIPTION = """Compass: live coding-agent session activity across harnesses.

Stdlib-only local server. Supported harnesses (each shown only if its local
data is discovered): Claude Code, Codex, Pi, Gemini CLI (retired, legacy
stores only), Antigravity CLI, GitHub Copilot CLI, OpenCode, Cursor CLI,
Goose, Factory Droid. Serves a summary UI at http://127.0.0.1:<port>/ and
JSON at /api/data.
"""

LAUNCHER_PATH = Path(__file__).resolve().parents[1] / "server.py"
# scripts/package-cli.sh writes the release version here. The binary is built before the release
# job bumps the manifests, so the plugin manifest still names the previous release at that point.
BUNDLED_VERSION_PATH = Path(__file__).with_name("release-version.txt")
PLUGIN_MANIFEST_PATH = Path(__file__).resolve().parents[3] / ".claude-plugin" / "plugin.json"
TOOL_OUTPUT_ENV = "COMPASS_ALLOW_TOOL_OUTPUT"


def collected_session_ids(application: aggregate.Application) -> frozenset[str]:
    """Freeze collected identities before registration can cause effects."""
    _revision, body = application.collect_json(show_all=True)
    try:
        payload = json.loads(body)
    except (ValueError, json.JSONDecodeError):
        return frozenset()
    rows = payload.get("sessions") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        return frozenset()
    return frozenset(
        f"{row['harness']}:{row['sid']}"
        for row in rows
        if isinstance(row, dict)
        and isinstance(row.get("harness"), str)
        and isinstance(row.get("sid"), str)
    )


def build_server(
    address: tuple[str, int],
    application: aggregate.Application,
    page_bytes: bytes,
    coordinator: observation.Observation | None,
    *,
    interaction_session: str | None,
    interaction_registration_file: Path | None,
) -> http_api.CompassHTTPServer:
    """Attach the opt-in collected-session origin without changing normal serving."""
    prototype = None
    if interaction_session is not None:
        known_sessions = collected_session_ids(application)
        prototype = runtime_interaction.InteractionPrototype(
            collected_session_id=interaction_session,
            session_exists=known_sessions.__contains__,
            registration_file=interaction_registration_file,
        )
    return http_api.CompassHTTPServer(
        address,
        application,
        page_bytes,
        coordinator,
        interaction_prototype=prototype,
    )


def runtime_environ(home: str | None = None) -> dict[str, str]:
    """Capture ambient process inputs at the executable boundary.

    The one place the environment is read. Everything downstream takes the
    result as an argument, which is what lets the whole runtime be exercised
    for another platform on any runner (design decision
    [D-4](docs/design-cross-platform.md#d-4)).
    """
    environ = dict(os.environ)
    resolved_home = os.path.expanduser("~") if home is None else home
    environ["HOME"] = resolved_home
    if sys.platform == "win32":
        environ["USERPROFILE"] = resolved_home
    return environ


# The two binds the rest of the runtime works against. Not a taste for round
# numbers: everything that talks *to* the server talks to loopback, and loopback
# is an interface of both of these and of nothing else. `--status` and `--stop`
# probe `127.0.0.1:<port>`; the four hook forwarders and the MCP server refuse a
# non-loopback destination by design (SECURITY.md's first invariant); the
# announced URL is loopback. A single-interface bind like `--host 10.0.0.2`
# leaves all of them talking to a closed port, and the worst of them is not the
# dead hook — `--stop` reads "not running", exits 0, and deletes the live
# instance's state file, event-ingress capability tokens and all, while the
# server keeps serving. Binding one interface is a reasonable thing to want; it
# needs the bind address threaded through the state file and every client, and
# refusing it is the honest answer until that exists.
BIND_HOSTS = ("127.0.0.1", "0.0.0.0")  # noqa: S104 — the documented wildcard opt-in


def bind_host(value: str) -> str:
    """An argparse type for the dashboard's bind address.

    Two accepted values, and IPv6 is not among them: the server is IPv4-only, so
    ``::`` or ``::1`` is out of scope and rejected at parse time rather than
    becoming a confusing bind failure. See ``BIND_HOSTS`` for why a single
    non-loopback interface is refused rather than allowed and left broken.

    ``ipaddress`` rather than a hand-rolled dotted-quad split, which is where
    this started: ``int()`` accepts a sign, surrounding whitespace and
    non-ASCII digits, so ``"+1.2.3.4"`` and ``"1.2.3.4\n"`` parsed and then
    reached ``socket.bind`` — the confusing bind failure the check exists to
    turn into a usage error.
    """
    try:
        ipaddress.IPv4Address(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"must be an IPv4 address, one of {' or '.join(BIND_HOSTS)}"
        ) from exc
    if value not in BIND_HOSTS:
        raise argparse.ArgumentTypeError(
            f"must be {' or '.join(BIND_HOSTS)}. A single-interface bind is refused rather "
            "than half-supported: --status, --stop, the hook forwarders and the MCP server all "
            "reach the dashboard over loopback, which such a bind does not answer"
        )
    return value


def positive_float(value: str) -> float:
    """A float above zero, or an argparse error naming what was wrong.

    Zero or negative is refused rather than clamped: a retention window of zero
    days is a store that evicts everything it records, which reads as the store
    being broken rather than as the operator having turned it off — and there is
    already a switch that turns it off. Rejected at parse time, so a daemon
    cannot be respawned with a bound the parent would not have accepted.
    """
    try:
        number = float(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{value!r} is not a number") from None
    if not math.isfinite(number) or number <= 0:
        raise argparse.ArgumentTypeError(f"must be greater than zero, not {value!r}")
    return number


def positive_int(value: str) -> int:
    """An int above zero, or an argparse error naming what was wrong."""
    try:
        number = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{value!r} is not a whole number") from None
    if number <= 0:
        raise argparse.ArgumentTypeError(f"must be greater than zero, not {value!r}")
    return number


def claude_reading_model_arg(value: str) -> str:
    """An invalid CLI value is refused without copying it into diagnostics."""
    try:
        return runtime_config.validate_claude_reading_model(value)
    except ValueError as error:
        msg = "Choose an explicit Claude Sonnet or Opus generation 5 or later model ID."
        raise argparse.ArgumentTypeError(msg) from error


def release_version() -> str | None:
    """The Compass version: the stamp a standalone binary carries, else the plugin manifest."""
    try:
        stamped = BUNDLED_VERSION_PATH.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError):
        stamped = ""
    if stamped:
        return stamped
    try:
        manifest = json.loads(PLUGIN_MANIFEST_PATH.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError):
        return None
    version = manifest.get("version") if isinstance(manifest, dict) else None
    return version if isinstance(version, str) and version else None


def print_version() -> int:
    version = release_version()
    if version is None:
        print("Compass: this installation does not record its version", file=sys.stderr)
        return 1
    print(version)
    return 0


def build_parser() -> argparse.ArgumentParser:
    """The CLI surface. argparse owns --help and its own usage errors."""
    # Abbreviations are off so a removed option stays refused: `--frontend` is a unique prefix of
    # `--frontend-dev-manifest`, and a habit from the retired renderer switch (`--frontend react`)
    # would otherwise be read as a development ticket path instead of an unknown option.
    parser = argparse.ArgumentParser(description=DESCRIPTION, allow_abbrev=False)
    parser.add_argument("--version", action="store_true", help="print the Compass version and exit")
    parser.add_argument("--port", type=lifecycle.tcp_port, default=4553)
    parser.add_argument(
        "--frontend-dev-manifest",
        type=Path,
        help="owned contributor Vite startup ticket; requires a foreground server on loopback",
    )
    parser.add_argument(
        "--host",
        type=bind_host,
        default="127.0.0.1",
        help="bind address: 127.0.0.1 (default) or 0.0.0.0 for remote access",
    )
    parser.add_argument(
        "--diagnose",
        action="store_true",
        help="report where each harness's data is searched for, and exit",
    )
    parser.add_argument(
        "--observer-model",
        action="store_true",
        help="accepted for one release; does nothing and will be removed in a later release",
    )
    parser.add_argument(
        "--claude-reading-model",
        type=claude_reading_model_arg,
        default=runtime_config.CLAUDE_READING_DEFAULT_MODEL,
        help=(
            "explicit Claude reading model; Sonnet/Opus generation 5 or later (default Sonnet 5.5)"
        ),
    )
    parser.add_argument(
        "--no-observer-model",
        "--no-harness-usage",
        action="store_true",
        help=(
            "refuse every model call for this run, "
            "overriding --observer-model and --unasked-readings"
        ),
    )
    parser.add_argument(
        "--allow-tool-output",
        action="store_true",
        help=(
            "accepted for one release; does nothing and will be removed in a later release; "
            f"{TOOL_OUTPUT_ENV}=1 is also accepted and does nothing"
        ),
    )
    parser.add_argument("--json", action="store_true", help="machine-readable --diagnose output")
    parser.add_argument(
        "--no-tripwires",
        action="store_true",
        help="Do not read or write saved workflow stage conditions.",
    )
    parser.add_argument(
        "--no-spacedock",
        action="store_true",
        help="do not read Spacedock workflow definitions (drops the stage strips)",
    )
    parser.add_argument(
        "--no-usage",
        action="store_true",
        help=(
            "for this run, do not fetch vendor quota over the network and do "
            "not publish quota a harness pushed in, regardless of the "
            "dashboard's stored setting. Quota a harness writes into its own "
            "store (Codex, Copilot) still shows"
        ),
    )
    parser.add_argument(
        "--no-git",
        action="store_true",
        help=(
            "do not run the end-of-session git probe in any session's working "
            "repository (the dirty and changed fields then stay empty)"
        ),
    )
    parser.add_argument(
        "--no-focus",
        action="store_true",
        help=(
            "do not raise a session's terminal for this run: no focus command "
            "runs, no terminal identity is recorded, and the page is handed no "
            "capability to ask with. --no-events turns it off as well"
        ),
    )
    parser.add_argument(
        "--no-history",
        action="store_true",
        help=(
            "do not keep a local history of what this server observed for this "
            "run: nothing is written and an existing store is not read back, so "
            "the board opens with no memory of earlier sessions."
        ),
    )
    parser.add_argument(
        "--no-dismiss",
        action="store_true",
        help=(
            "do not read or write the dismissal store for this run: sessions "
            "marked handled come back onto the board and the page offers no "
            "control to clear them. The rollback switch for the dismissal store "
            "Compass writes on your behalf"
        ),
    )
    parser.add_argument(
        "--no-annotations",
        action="store_true",
        help=(
            "do not read or write the annotation store for this run: the goal "
            "and expected output you typed against a session are neither shown "
            "nor saved, and the page offers no field to type them in. The "
            "rollback switch for the one store holding prose you composed "
            "rather than anything a harness published"
        ),
    )
    parser.add_argument(
        "--unasked-readings",
        action="store_true",
        help=(
            "check annotated sessions against what you asked for without being "
            "asked, and raise a departure through the notification lane. OFF by "
            "default and the only feature here that spends your model capacity "
            "with nobody watching: each check uses Claude Code or Codex, bounded per "
            "session and per day, and only a departure is ever raised. A check "
            "uses the session's own provider for Claude Code and Codex, and prefers "
            "Claude Code elsewhere, falling back only when unavailable. Codex needs "
            "the Drift card's 'Allow Codex to run unasked checks' toggle for the "
            "current destination. Checks send your typed goal and bounded reader messages "
            "through your signed-in CLI to where its settings send them, with no agent "
            "messages, outcome lines or tool output. Claude Code also sends its working "
            "directory, platform, shell, OS version, date and device identifier, and under "
            "a Claude account sign-in your email address and account ID. "
            "Pause model calls stops checks too. "
            "--no-observer-model refuses it for the run"
        ),
    )
    parser.add_argument(
        "--no-ask",
        action="store_true",
        help=(
            "do not let a session ask the reader a question for this run: the "
            "register, poll and answer routes refuse and the page offers no "
            "control. The rollback switch for the one feature that answers a "
            "waiting agent"
        ),
    )
    parser.add_argument(
        "--no-reach",
        action="store_true",
        help=(
            "do not send off-machine nudges for this run, regardless of the "
            "configured webhook URL. The off switch for the one pathway that "
            "reaches outside this machine"
        ),
    )
    parser.add_argument(
        "--reach-url",
        help="webhook endpoint for off-machine nudges when a session needs human attention",
    )
    parser.add_argument(
        "--quiet-hours",
        help=(
            "time window (HH:MM-HH:MM in 24-hour local time) during which non-ask "
            "notifications and nudges are suppressed (e.g. 22:00-08:00 or 13:00-14:00)"
        ),
    )
    parser.add_argument(
        "--no-quiet-hours",
        action="store_true",
        help=(
            "do not suppress notifications for quiet hours for this run, "
            "regardless of the stored setting or environment variable"
        ),
    )
    parser.add_argument(
        "--no-irreversible",
        action="store_true",
        help="disable hook command-shape matching, report ingress and publication for this run",
    )
    parser.add_argument(
        "--no-events",
        action="store_true",
        help=(
            "do not run the event coordinator for this run: no event overlays, "
            "no coarse store probe, and the older fixed-interval producer keeps "
            "the snapshot warm instead. The independent rollback switch if event "
            "acquisition misbehaves"
        ),
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="report whether a Compass is running on --port, and exit",
    )
    parser.add_argument(
        "--stop",
        action="store_true",
        help="stop the Compass running on --port, and exit",
    )
    parser.add_argument(
        "--forget",
        action="store_true",
        help=(
            "delete local observation stores and session summaries, and exit. Refused while a "
            "dashboard is running on --port, which would write it back"
        ),
    )
    parser.add_argument(
        "--daemon",
        action="store_true",
        help="detach and keep running after the session that started it exits",
    )
    parser.add_argument(
        "--window-hours",
        type=float,
        default=24,
        help="sessions with no activity in this window are hidden (default 24)",
    )
    parser.add_argument(
        "--interaction-origin-session",
        help="bind one explicitly registered collected harness:sid to read-only output",
    )
    parser.add_argument(
        "--interaction-origin-registration-file",
        type=Path,
        help="write the one-use session-side tmux registration capability here",
    )
    parser.add_argument(
        "--history-days",
        type=positive_float,
        default=runtime_config.HISTORY_RETENTION_DEFAULT_DAYS,
        help=(
            "how long the local history keeps an observation, in days "
            f"(default {runtime_config.HISTORY_RETENTION_DEFAULT_DAYS:g}). Eviction is by "
            "age first, so narrowing this drops what falls outside it and "
            "widening it again brings nothing back"
        ),
    )
    parser.add_argument(
        "--history-max-bytes",
        type=positive_int,
        default=runtime_config.HISTORY_MAX_BYTES_DEFAULT,
        help=(
            "the size cap on the local history store, in bytes (default "
            f"{runtime_config.HISTORY_MAX_BYTES_DEFAULT}). It is the read cap too: a "
            "file larger than it is discarded unread rather than parsed"
        ),
    )
    return parser


def build_runtime(
    args: argparse.Namespace,
    *,
    started: float,
    launcher_path: Path = LAUNCHER_PATH,
) -> tuple[RuntimeConfig, RuntimeState]:
    """Freeze configuration and create state, with no operational side effects.

    Nothing here touches a store, a socket, or a log. That is what makes
    --diagnose, --status and --stop usable on a machine where serving would
    fail.
    """
    environ = runtime_environ()
    config = runtime_config.build_runtime_config(
        environ=environ,
        platform_name=sys.platform,
        os_name=os.name,
        launcher_path=launcher_path,
        host=args.host,
        port=args.port,
        window_hours=args.window_hours,
        spacedock_enabled=not args.no_spacedock,
        tripwires_enabled=not args.no_tripwires,
        usage_fetch_enabled=not args.no_usage,
        observer_model_enabled=not args.no_observer_model,
        model_calls_disabled=args.no_observer_model,
        claude_reading_model=args.claude_reading_model,
        git_probe_enabled=not args.no_git,
        focus_enabled=not args.no_focus,
        irreversible_enabled=not args.no_irreversible and not args.no_events,
        dismissals_enabled=not args.no_dismiss,
        annotations_enabled=not args.no_annotations,
        # The lane reads typed goals, which `--no-annotations` turns off, and the
        # Codex toggle is refused there: publishing either would draw a control
        # that can never work.
        unasked_enabled=args.unasked_readings
        and not args.no_observer_model
        and not args.no_annotations,
        ask_enabled=not args.no_ask,
        reach_enabled=not args.no_reach,
        reach_url=args.reach_url,
        quiet_hours_enabled=not getattr(args, "no_quiet_hours", False),
        quiet_hours=getattr(args, "quiet_hours", None),
        history_enabled=not args.no_history,
        history_retention_sec=args.history_days * runtime_config.SECONDS_PER_DAY,
        history_max_bytes=args.history_max_bytes,
    )
    return config, runtime_state.build_runtime_state(config, started=started)


def bound_popup_notifier(
    config: RuntimeConfig,
    diagnostic_sink: Callable[[str], None],
) -> Callable[[str, str], str | None]:
    """The application's popup notifier: config and sink bound, two arguments left.

    Returns the outcome rather than `None`, so the caller that spends the
    cooldown can record what became of the raise it spent it on.
    """

    def notify(title: str, message: str) -> str:
        return notifications.notify_mac(config, title, message, diagnostic_sink=diagnostic_sink)

    return notify


def build_application(
    config: RuntimeConfig,
    state: RuntimeState,
    *,
    diagnostic_sink: Callable[[str], None] = print,
    clock: Callable[[], float] = time.time,
    record_history: bool = True,
    frontend_page_bytes: bytes | None = None,
) -> aggregate.Application:
    """One application over one config and state, with every service injected.

    `record_history` is the one service a caller has to think about, and only
    one caller says no to it: `--diagnose` reports what the stores hold and must
    not write while doing it. Attached unconditionally, one `--diagnose` into a
    clean `COMPASS_HOME` created a 26,086-byte store of 189 records spanning
    13.41 days — 176 of them outside `window_hours` and unreachable from a
    serving collection — and `--forget && --diagnose` put back the file the
    delete had just removed.

    The unasked reading lane rides the same switch and adds one of its own, the
    ruling being
    [DEC-18](docs/design-reading-a-session.md#dec-18-an-unasked-reading-is-permitted-and-gated-on-delivery-first).
    """
    popup_notifier = (
        (lambda _title, _message: deliveries.OUTCOME_NO_LANE)
        if config.frontend_dev is not None
        else bound_popup_notifier(config, diagnostic_sink)
    )
    application = aggregate.Application(
        config,
        state,
        aggregate.default_harnesses(usage_fetch_enabled=config.usage_fetch_enabled),
        native_notifier=(lambda _: "")
        if config.frontend_dev is not None
        else notifications.native_notifier,
        popup_notifier=popup_notifier,
        diagnostic_sink=diagnostic_sink,
        clock=clock,
        frontend_page_bytes=frontend_page_bytes,
    )
    if record_history:
        # Attached here rather than reached through the overlay source, which is
        # None forever under --no-events: the store's only off switch is
        # --no-history, so the lane must not hang off an unrelated flag.
        application.history_lane = history.Lane(config, diagnostic_sink=diagnostic_sink)
    if record_history and config.unasked_enabled:
        # Two conditions and both are load bearing. `--diagnose` passes
        # `record_history=False` and runs a collection, which must not start a
        # `codex` subprocess while reporting what the stores hold; and the
        # switch is off by default under the ruling cited in this function's
        # docstring, so an installed board never spends the reader's capacity
        # unless they asked it to. It shares
        # `record_history` with the history lane rather than owning a second
        # is-this-diagnose signal, which is the thing there must not be two of.
        application.unasked_lane = unasked.Lane(
            config,
            popup_notifier=popup_notifier,
            # The registry's own display label, so a departure banner says what
            # the board says. Without it a row badged Antigravity produced a
            # notification headed `antigravity`.
            harness_label=application.harness_label,
            diagnostic_sink=diagnostic_sink,
            clock=clock,
        )
    return application


def load_frontend_page() -> bytes | None:
    """Load the dashboard page, or say why it cannot be served.

    A failure serves nothing rather than a stand-in: a dashboard that looks fine over a
    damaged installation would hide the damage.
    """
    try:
        return frontend_page.load_frontend_page()
    except (OSError, UnicodeError, RuntimeError) as exc:
        print(
            f"Compass: cannot load frontend assets ({type(exc).__name__}: {exc}).",
            file=sys.stderr,
        )
        print("Compass: reinstall the plugin to repair this build.", file=sys.stderr)
        return None


def validate_interaction_args(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    """Reject a partial collected-session registration boundary."""
    if bool(args.interaction_origin_session) != bool(args.interaction_origin_registration_file):
        parser.error(
            "--interaction-origin-session and --interaction-origin-registration-file "
            "must be used together"
        )


def validate_frontend_args(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    if args.frontend_dev_manifest is None:
        return
    if args.host != "127.0.0.1" or args.daemon or args.diagnose or args.forget:
        parser.error(
            "development frontend requires a foreground server on 127.0.0.1; "
            "diagnose/forget are not development commands"
        )
    for name in (
        "no_observer_model",
        "no_usage",
        "no_git",
        "no_focus",
        "no_events",
        "no_spacedock",
        "no_tripwires",
        "no_reach",
        "no_ask",
        "no_history",
    ):
        setattr(args, name, True)


def prepare_frontend(
    config: RuntimeConfig, args: argparse.Namespace
) -> tuple[RuntimeConfig, bytes | None]:
    if args.frontend_dev_manifest is None:
        return config, load_frontend_page()
    try:
        dev = frontend_dev.admit(args.frontend_dev_manifest, config)
        return dataclasses.replace(config, frontend_dev=dev), frontend_dev.load_page(dev)
    except RuntimeError as exc:
        print(f"Compass: cannot admit development frontend ({exc}).", file=sys.stderr)
        return config, None


FOCUS_META_NAME = "compass-focus"
# The focus consumer key is hex, so nothing legitimate is turned away and nothing
# that could close the attribute or open a tag gets in. Checked rather than
# escaped: an escape would make an unexpected token renderable, and a token this
# server did not mint is a bug rather than a value to accommodate.
_FOCUS_TOKEN_CHARS = frozenset("0123456789abcdefABCDEF")


def inject_focus_capability(page: bytes, token: str) -> bytes:
    """Put this run's focus capability into the served document.

    Injected here rather than baked into an asset, and the seam matters: the
    page's bytes are verified against `react.integrity.json`, so a token inside
    `compass_runtime/web/` would break that check and make the page
    non-deterministic. This runs between `load_frontend_page()` and the server
    construction, which leaves the verified bytes untouched.

    Returns the page unchanged when there is nothing safe to inject, because a
    page with no control is the documented off state rather than an error.
    """
    if not token or not set(token) <= _FOCUS_TOKEN_CHARS:
        return page
    marker = b"</head>"
    index = page.find(marker)
    if index < 0:
        return page
    meta = f'<meta name="{FOCUS_META_NAME}" content="{token}">'.encode()
    return page[:index] + meta + page[index:]


def run_one_shot(
    args: argparse.Namespace,
    config: RuntimeConfig,
    state: RuntimeState,
) -> int | None:
    """The commands that report and exit, or None when this run is to serve.

    Gathered out of `main` rather than left as four consecutive branches there,
    because `main` sits on ruff's branch cap and `--forget` was the flag that
    put it over. They are one family: each answers a question or performs one
    irreversible act, none of them binds a socket, and `--daemon` is refused
    with all four.
    """
    if args.diagnose:
        # No recording lane: diagnostics read the stores and report, and
        # `SKILL.md` sends the reader here first whenever a harness is missing.
        report = diagnostics.diagnose(build_application(config, state, record_history=False))
        runtime_io.diag(
            json.dumps(report, indent=2) if args.json else diagnostics.render_diagnosis(report),
            print,
        )
        return 0
    if args.forget:
        # In the family of --stop and --status rather than the family of per-run
        # switches, because what it does is not reversible by running the next
        # command without it. It deletes the file whether or not the store is
        # enabled, and it adds no route: nothing over the loopback port can
        # delete history.
        path = history.store_path(config)
        ends_path = ends.store_path(config)
        annotations_path = annotation_store.store_path(config)
        summaries_path = summary_store.store_path(config)
        # Refused while an instance is up, because a running dashboard holds its
        # own baseline in memory and republishes it on the next transition: the
        # delete reported success and every record came back. The probe is the
        # one `--status` and `--stop` already use, so it needs neither the home
        # the dashboard was started with nor a state file. It covers the port
        # this invocation names and cannot see an instance on another one, which
        # is why the lane also drops a baseline whose file has gone.
        if lifecycle.instance_status(config, args.port)["state"] == "running":
            # All three files, because the refusal keeps all three (DRC-4547,
            # DRC-4565): a reader who ran this to drop a recorded end is owed
            # the end store's name, and one who ran it for the discard records
            # is owed the annotation store's. A sentence naming the history
            # store alone reads as though the rest had gone.
            #
            # The clauses differ because the reasons do, and the third is not
            # the first two. The history lane would write its baseline back and
            # the coordinator would go on publishing the ends it still holds,
            # so those two would be undone. The annotation store would not: every
            # mutator re-reads the file inside the lock and `refresh` picks a
            # sweep up on the next collection, which is the deliberate opposite
            # of `history.Lane`. What is true of it is simply that the sweep did
            # not run, because this command refuses whole rather than in parts.
            runtime_io.diag(
                f"Compass: a dashboard is running on port {args.port} and would "
                f"write {path} back from memory and go on publishing the ends in "
                f"{ends_path}; the summaries in {summaries_path} and discard records "
                f"in {annotations_path} were not "
                "swept either, because the command refuses whole; stop it with "
                "--stop first, then --forget",
                print,
            )
            return 1
        runtime_io.diag(
            f"Compass: deleted {path}"
            if history.forget(config)
            else f"Compass: no history store at {path}",
            print,
        )
        # The session-end store goes with it (decisions.md, DRC-4547): the
        # command removes the machine's memory of what it observed, and an end
        # this board saw is exactly that class. The running-instance refusal
        # above covers it too, for a neighbouring reason: the coordinator does
        # not republish its memory the way the history lane does, but it still
        # holds the ends it observed and publishes them on every collection, so
        # the delete would change the file and not the board.
        runtime_io.diag(
            f"Compass: deleted {ends_path}"
            if ends.forget(config)
            else f"Compass: no session-end store at {ends_path}",
            print,
        )
        # And the records of what this machine deleted (DRC-4565). A sweep and
        # not a delete, which is the distinction the whole command rests on:
        # a record that Compass discarded something is its memory of an act it
        # observed, and the words a reader typed are not -- `annotations`'
        # docstring says `--forget` does not reach those and it still does not.
        #
        # Three sentences and not two, because a sweep has three answers: an
        # unwritable store still holds every record, and reporting that as
        # "no discard records" is the one wrong sentence this command can say.
        # `forget` silences the store's own failure line so this one stands
        # alone; that line is worded for a reader losing what they typed, and
        # here nothing was written and nothing was lost.
        swept = annotation_store.forget(config)
        runtime_io.diag(
            {
                annotation_store.FORGET_SWEPT: (
                    f"Compass: removed the discard records in {annotations_path}"
                ),
                annotation_store.FORGET_NOTHING: (
                    f"Compass: no discard records in {annotations_path}"
                ),
                annotation_store.FORGET_UNWRITABLE: (
                    f"Compass: could not write {annotations_path}, so its discard "
                    "records are still there"
                ),
                annotation_store.FORGET_UNTRUSTED: (
                    f"Compass: {annotations_path} could not be read, so nothing in it was "
                    "changed; move or repair that file and run --forget again"
                ),
            }[swept],
            print,
        )
        # The digests of corrections the reader copied (DRC-4678): no text, and
        # the machine's memory of an act, the class the discard records are in.
        # Deleted with the other two, and the refusal above returns before it.
        copies_path = copied_corrections.store_path(config)
        runtime_io.diag(
            f"Compass: deleted {copies_path}"
            if copied_corrections.forget(config)
            else f"Compass: no copied-correction store at {copies_path}",
            print,
        )
        summary_outcome = summary_store.forget(config)
        runtime_io.diag(
            f"Compass: summary store {summaries_path}: {summary_outcome}",
            print,
        )
        permission_forgotten = reading_policy.forget(config)
        runtime_io.diag(
            "Compass: forgot reading permission; unexpired spend timestamps remain"
            if permission_forgotten
            else "Compass: could not forget reading permission; the store is unavailable",
            print,
        )
        return 0 if permission_forgotten and summary_outcome != "unwritable" else 1
    if args.stop:
        message, code = lifecycle.stop_instance(config, args.port)
        runtime_io.diag(message, print)
        return code
    if args.status:
        status = lifecycle.instance_status(config, args.port)
        runtime_io.diag(lifecycle.render_status(status), print)
        return 0 if status["state"] == "running" else 1
    return None


def main(argv: Sequence[str] | None = None) -> int:
    """Parse, assemble, and run. Returns an exit code.

    argparse keeps its own SystemExit for --help and usage errors; every other
    exit is a returned code, so the CLI is callable from a test without
    catching SystemExit.
    """
    lifecycle.unignore_sigterm()
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.version:
        return print_version()
    # Sampled before the combination check: the start stamp names this process,
    # and must not shift depending on which validation ran first.
    started = time.time()
    if args.daemon and (args.diagnose or args.stop or args.status or args.forget):
        # Each of those four exits without serving, so --daemon cannot apply.
        # Accepting it silently would teach that it had been honored.
        parser.error("--daemon cannot be combined with --diagnose, --stop, --status or --forget")
    validate_interaction_args(parser, args)
    validate_frontend_args(parser, args)
    config, state = build_runtime(args, started=started)

    one_shot = run_one_shot(args, config, state)
    if one_shot is not None:
        return one_shot

    if not runtime_io.sqlite_available():
        runtime_io.diag(
            f"Compass: sqlite3 unavailable ({runtime_io.SQLITE_IMPORT_ERROR}) — OpenCode, "
            "Cursor and Goose sessions cannot be read; Antigravity still appears "
            "but without its token rate or turn ETA. Install the sqlite3 "
            "extension for this interpreter to enable them.",
            print,
        )
    # After the recovery commands above, so --status and --stop still work on an
    # installation whose assets are missing, and while stderr is still attached.
    config, page_bytes = prepare_frontend(config, args)
    state.config = config
    if page_bytes is None:
        return 1
    lifecycle.sweep_stale_states(config)
    observer.sweep_claude_scratch(config)
    log_file = lifecycle.log_path(config, args.port)
    if args.daemon and not lifecycle.prepare_daemon_home(config, log_file):
        # Reported already; the message has to reach the terminal that asked,
        # which is why this is checked before anything detaches.
        return 1

    if args.daemon and config.os_name == "nt":
        # No fork on Windows: re-spawn, then wait to be sure
        # ([D-2](docs/design-daemon.md#d-2)).
        # This branch returns before any bind, so the parent never holds the port it handed
        # over, and never constructs a server at all — the spawned foreground
        # child owns the bind and therefore owns reporting a bind failure.
        message, code = lifecycle.await_spawned(
            config,
            lifecycle.spawn_detached(config, args, log_file),
            args.port,
            log_file,
        )
        runtime_io.diag(message, print)
        return code

    # Bind before detaching. bind_error_message() exists so a busy port gets an
    # explanation rather than a traceback, and SKILL.md tells the agent to look
    # for an already-running dashboard when it sees one. Forking first would
    # send that message to a log file nobody has been told about yet, and
    # report success.
    try:
        application = build_application(config, state, frontend_page_bytes=page_bytes)
        # Constructed inert and attached both ways: the coordinator reads the
        # application to collect, and the application reads the coordinator for
        # overlays. Nothing has started a thread yet, which is what lets the
        # daemon fork below happen safely.
        coordinator = None
        if not args.no_events:
            coordinator = observation.Observation(application)
            application.overlays = coordinator
        if coordinator is not None and config.focus_enabled:
            # The page is served as fixed bytes with no per-run secret in it, so
            # the capability has to be put there. `--no-events` leaves no
            # coordinator to mint one, which is the second off switch the focus
            # contract names.
            page_bytes = inject_focus_capability(page_bytes, coordinator.focus_capability())
        server = build_server(
            (args.host, args.port),
            application,
            page_bytes,
            coordinator,
            interaction_session=args.interaction_origin_session,
            interaction_registration_file=args.interaction_origin_registration_file,
        )
    except OSError as exc:
        runtime_io.diag(http_api.bind_error_message(exc, args.port, args.host), print)
        return 1

    announce_fd: int | None = None
    if args.daemon:
        role, fd = lifecycle.fork_daemon()
        if role == "parent":
            # The daemon holds its own dup of the listening socket; closing
            # this one keeps a dead daemon from leaving the port looking bound.
            with contextlib.suppress(OSError):
                server.server_close()
            message, code = lifecycle.await_daemon(config, fd, args.port, log_file)
            runtime_io.diag(message, print)
            return code
        announce_fd = fd
        lifecycle.daemon_redirect_stdio(log_file)

    lifecycle.serve(config, server, args.port, started=started, announce_fd=announce_fd)
    return 0
