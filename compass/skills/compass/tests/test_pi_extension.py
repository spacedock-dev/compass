"""Execute the shipped Pi subscriber, not a second envelope implementation."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from typing import Any

from compass_runtime import events, observation, sessions

from . import SKILL_DIR, support

SESSION = "abcdef12-3456-7890-abcd-ef1234567890"


@unittest.skipUnless(shutil.which("node"), "node not available")
class PiExtensionTest(unittest.TestCase):
    def run_adapter(self, action: str) -> dict[str, Any]:
        with tempfile.TemporaryDirectory() as directory:
            code = (
                """
import {createServer} from 'node:http';
import {writeFile, unlink} from 'node:fs/promises';
import {pathToFileURL} from 'node:url';
const messages = [], callbacks = {};
const server = createServer((req,res) => {
  let raw=''; req.on('data',chunk=>raw+=chunk);
  req.on('end',()=>{messages.push({path:req.url, token:req.headers['x-compass-capability'],
    body:JSON.parse(raw)}); res.end('{}');});
});
await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
process.env.COMPASS_PORT=String(server.address().port);
const state=process.env.COMPASS_HOME+'/compass-'+process.env.COMPASS_PORT+'.json';
await writeFile(state,JSON.stringify({capabilities:{pi:'a'.repeat(64)}}));
"""
                """
const adapter=await import(pathToFileURL(process.argv[1]));
adapter.default({on:(name,fn)=>callbacks[name]=fn});
const ctx={sessionManager:{getSessionId:()=> 'abcdef12-3456-7890-abcd-ef1234567890'}};
const pause=ms=>new Promise(resolve=>setTimeout(resolve,ms));
const emit=(name,kind='select',extra={})=>callbacks[name]({type:name,reason:'ui_prompt',kind,
  title:'private title', answer:'private answer',cwd:'/private/path',...extra},ctx);
"""
                + action
                + """
await pause(150);
console.log(JSON.stringify({messages, subscriptions:Object.keys(callbacks)}));
server.closeAllConnections(); await new Promise(resolve=>server.close(resolve));
"""
            )
            result = subprocess.run(
                [
                    str(shutil.which("node")),
                    "--input-type=module",
                    "-e",
                    code,
                    str(SKILL_DIR / "pi_extension.js"),
                ],
                capture_output=True,
                text=True,
                timeout=8,
                check=False,
                env={**os.environ, "COMPASS_HOME": directory},
            )
            self.assertEqual(0, result.returncode, result.stderr)
            return json.loads(result.stdout)  # type: ignore[no-any-return]

    @unittest.skipIf(os.name == "nt", "POSIX nofollow symlink admission")
    def test_a_linked_capability_file_cannot_send_a_permission_event(self) -> None:
        result = self.run_adapter("""
const {rename,symlink}=await import('node:fs/promises');
await rename(state,state+'.original'); await symlink(state+'.original',state);
emit('ui_prompt_start'); await pause(100);
const linkedMessages=messages.length;
await unlink(state); await rename(state+'.original',state);
emit('ui_prompt_start'); await pause(100);
if(linkedMessages!==0) throw new Error('linked capability sent an event');
""")
        self.assertEqual(1, len(result["messages"]))

    def test_measured_pair_for_all_five_kinds_omits_native_contents(self) -> None:
        result = self.run_adapter("""
for(const kind of ['select','confirm','input','editor','custom']) {
  emit('ui_prompt_start',kind); await pause(50);
  emit('ui_prompt_end',kind); await pause(50);
}
""")
        self.assertEqual(["ui_prompt_start", "ui_prompt_end"], result["subscriptions"])
        messages = result["messages"]
        self.assertEqual(10, len(messages))
        for index, message in enumerate(messages):
            self.assertEqual("/api/events/pi", message["path"])
            self.assertEqual("a" * 64, message["token"])
            body = message["body"]
            self.assertEqual(SESSION, body["session_id"])
            self.assertEqual("input_resolved" if index % 2 else "input_requested", body["event"])
            self.assertEqual(
                {"v", "event", "session_id", "timestamp", "source_instance_id", "source_sequence"},
                set(body),
            )
            self.assertEqual(index + 1, body["source_sequence"])
            parsed = events.parse(
                "pi",
                body,
                arrival_seq=index + 1,
                config=support.make_config(),
                now=support.SERVER_STARTED,
            )
            self.assertIsInstance(parsed, events.Event)
            assert isinstance(parsed, events.Event)
            self.assertEqual(SESSION, parsed.sid)
            overlay = events.overlay_for(parsed, config=support.make_config())
            assert overlay is not None
            patch = events.reduce_overlays([overlay], now=support.SERVER_STARTED)
            self.assertEqual("working" if index % 2 else "needs_input", patch["state"])

    def test_invalid_native_kind_identity_and_reason_do_not_send(self) -> None:
        result = self.run_adapter("""
emit('ui_prompt_start','trust');
emit('ui_prompt_start','select',{reason:'other'});
emit('ui_prompt_start','select',{type:'unknown'});
for(const id of ['', '../../private', '-'.repeat(36), 'a'.repeat(36), null]) {
  ctx.sessionManager.getSessionId=()=>id; emit('ui_prompt_start');
}
""")
        self.assertEqual([], result["messages"])

    def test_missing_malformed_oversized_and_disabled_state_do_not_send(self) -> None:
        result = self.run_adapter("""
await unlink(state); emit('ui_prompt_start'); await pause(30);
for(const value of ['invalid', '{}', 'null', ' '.repeat(65537),
  JSON.stringify({capabilities:{pi:'bad\\nheader'}}),
  JSON.stringify({capabilities:{opencode:'a'.repeat(64)}})]) {
  await writeFile(state,value); emit('ui_prompt_start'); await pause(30);
}
""")
        self.assertEqual([], result["messages"])

    # Both tests below hold a reply open and move on when the server has seen a
    # request, not after a fixed pause. The first version paused 110 ms against
    # an 80 ms reply: on a slow runner the first reply landed later, the end was
    # coalesced instead of sent, and the lists differed as
    # [requested, resolved, requested] versus [requested, requested]. Both are
    # correct; which one a run took was the runner's speed (DRC-4707).
    HELD_REPLY = """
server.removeAllListeners('request');
const log = [], held = [];
server.on('request',(req,res)=>{let raw=''; req.on('data',c=>raw+=c);
  req.on('end',()=>{const body=JSON.parse(raw); messages.push(body);
    log.push('received '+body.event);
    const reply=()=>{log.push('replied '+body.event); res.end('{}');};
    if(hold.has(messages.length)) held.push(reply); else reply();});});
const waitFor=async(ready)=>{const until=Date.now()+2000;
  while(!ready()) { if(Date.now()>until) throw Error('timed out: '+JSON.stringify(log));
    await pause(5); }};
"""

    def test_delayed_end_cannot_overtake_later_start(self) -> None:
        # The end is in flight with its reply held when the later start is
        # emitted. The 50 ms before the release is the window an overtaking
        # start would need; a start that waits never uses it.
        result = self.run_adapter(
            "const hold = new Set([2]);"
            + self.HELD_REPLY
            + """
emit('ui_prompt_start'); await waitFor(()=>messages.length>=1);
emit('ui_prompt_end'); await waitFor(()=>held.length===1);
emit('ui_prompt_start'); await pause(50); held[0]();
await waitFor(()=>messages.length>=3);
messages.push(log);
"""
        )
        *messages, log = result["messages"]
        self.assertEqual(
            ["input_requested", "input_resolved", "input_requested"],
            [item["event"] for item in messages],
        )
        self.assertEqual([1, 2, 3], [item["source_sequence"] for item in messages])
        self.assertEqual(
            [
                "received input_requested",
                "replied input_requested",
                "received input_resolved",
                "replied input_resolved",
                "received input_requested",
                "replied input_requested",
            ],
            log,
        )

    def test_an_end_queued_behind_a_report_is_superseded_by_the_next_start(self) -> None:
        # The other branch the timed version fell into: a close and a reopen
        # while the first report is still unanswered leave one queued state,
        # the later wait, rather than a close that would clear it.
        result = self.run_adapter(
            "const hold = new Set([1]);"
            + self.HELD_REPLY
            + """
emit('ui_prompt_start'); await waitFor(()=>held.length===1);
emit('ui_prompt_end'); emit('ui_prompt_start'); held[0]();
await waitFor(()=>messages.length>=2);
"""
        )
        self.assertEqual(
            ["input_requested", "input_requested"],
            [item["event"] for item in result["messages"]],
        )
        self.assertEqual([1, 3], [item["source_sequence"] for item in result["messages"]])

    def test_hanging_endpoint_bounds_burst_and_never_awaits_ui_callback(self) -> None:
        result = self.run_adapter("""
server.removeAllListeners('request');
server.on('request',(req,_res)=>{let raw=''; req.on('data',c=>raw+=c);
  req.on('end',()=>messages.push(JSON.parse(raw)));});
if(emit('ui_prompt_start') !== undefined) throw Error('UI callback awaited transport');
await pause(50);
for(let i=0;i<1000;i++) { emit('ui_prompt_end'); emit('ui_prompt_start'); }
emit('ui_prompt_end'); await pause(1100);
""")
        self.assertEqual(
            ["input_requested", "input_resolved"], [item["event"] for item in result["messages"]]
        )

    def test_stale_capability_response_is_not_retried_or_redirected(self) -> None:
        result = self.run_adapter("""
server.removeAllListeners('request');
server.on('request',(req,res)=>{messages.push(req.url);
  res.writeHead(403,{Location:'http://192.0.2.1/never'}); res.end();});
emit('ui_prompt_start'); await pause(650);
""")
        self.assertEqual(["/api/events/pi"], result["messages"])


class PiPublicationTest(support.RuntimeTestCase):
    def test_absent_disabled_and_restarted_reporter_are_unknown(self) -> None:
        app = support.build_app()
        now = support.SERVER_STARTED
        for harness in ("pi", "opencode"):
            for attached in (False, True):
                with self.subTest(harness=harness, attached=attached):
                    app.overlays = (
                        observation.Observation(app, clock=lambda: now) if attached else None
                    )
                    row = sessions.base_session(harness, SESSION, "controlled")
                    app._apply_overlays([row], now=now)
                    self.assertIn("block state", row["source_gaps"])

    def test_accepted_pi_pair_earns_coverage_but_heartbeat_does_not(self) -> None:
        app = support.build_app()
        now = support.SERVER_STARTED
        coordinator = observation.Observation(app, clock=lambda: now)
        app.overlays = coordinator
        for native, blocked, known in (
            ("store_changed", False, False),
            ("input_requested", True, True),
            ("input_resolved", False, True),
        ):
            self.assertEqual(
                "accepted",
                coordinator.submit(
                    "pi",
                    {
                        "v": 1,
                        "event": native,
                        "session_id": SESSION,
                    },
                ),
            )
            row = sessions.base_session("pi", SESSION, "controlled")
            app._apply_overlays([row], now=now)
            self.assertEqual(blocked, row["state"] == "needs_input")
            self.assertEqual(known, "block state" not in row["source_gaps"])
        app.overlays = observation.Observation(app, clock=lambda: now)
        row = sessions.base_session("pi", SESSION, "controlled")
        app._apply_overlays([row], now=now)
        self.assertIn("block state", row["source_gaps"])
