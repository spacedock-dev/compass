# The owned-process observer

SECURITY.md's [What launches and what sends](../SECURITY.md#what-launches-and-what-sends) pins every
outbound and launch path by test, against Compass's own code with the leaving call patched. Those
tests stop at the gate. Once Compass has started the Claude Code or Codex CLI, they cannot see what
that program connects to. They also miss a connection a dependency makes below the patched call, and
they cannot say which process did what. [What the tests do not see, and what a live capture would
add](../SECURITY.md#what-the-tests-do-not-see-and-what-a-live-capture-would-add) names the live
capture that would close the gap. This record covers the recorder that capture needs. It describes
what the recorder sees and what it cannot, and how to drive the five journey runs with it.

Nothing here ships. The three files live under `scripts/`, outside every plugin root, and a test
fails if a shipped file names any of them.

## Why it records from inside the owned process tree

Two earlier attempts failed. Sampling the process table once a second missed all twenty short
connections in a control run. DTrace and packet capture need privileges this machine refuses, and
changing a security setting to get them is not on the table. A machine-wide capture would also
record every other program's traffic, which is more than the question asks for and not ours to
record.

The question is narrower: what does one Compass server, and the programs it starts, launch and
connect to. The recorder therefore runs inside that process tree and needs no privilege.

- In the server, `scripts/owned_observer.py exec -- server.py ...` installs a Python audit hook
  (`sys.addaudithook`) and then runs `server.py` as `__main__` in the same interpreter. The hook
  writes one JSON line for each program launch (`subprocess.Popen`, `os.posix_spawn`, `os.exec`,
  `os.spawn`, `os.system`, `os.fork`), socket connect, unconnected `sendto`, name lookup, and
  `http.client` or `urllib` request. A small wrapper on `subprocess.Popen` adds each child's pid
  and its exit, so a launch has a duration.
- For every Node or Bun descendant, the server's environment carries
  `NODE_OPTIONS=--require=…/owned_observer_preload.js` and `BUN_OPTIONS=--preload=…`. Both
  variables are inherited, so each Node or Bun program in the tree loads the preload before its own
  code and hands it on to its children. The preload wraps `net.Socket.prototype.connect` (every
  Node TCP and TLS client, `http`, `https` and `fetch` included), `http`/`https` `request` and
  `get`, `fetch` and `Bun.fetch`, `WebSocket`, `Bun.connect`, `dns.lookup`, the `child_process`
  launchers, and `Bun.spawn`. It records start and exit too.

Both sides write synchronously to one append-only file, and they write before the recorded call
runs. A connection that lasts a millisecond still gets its line. That is the property sampling
lacked.

`BUN_OPTIONS` was not optional. Claude Code 2.1.314 is a Bun 1.4.4 executable, measured by loading a
marker preload under `claude --version`. It ignores `NODE_OPTIONS=--require` and loads a preload
named in `BUN_OPTIONS`. Without that variable the reading model's own requests would be invisible.

## It is off unless asked

- `exec` refuses with exit status 2, and runs nothing, unless `COMPASS_OBSERVE_LOG` names a file.
- `server.py` started the ordinary way never reads that variable, even when it is set, because the
  hook is installed by `exec` and nothing in `compass_runtime` imports the observer.
- The preload returns at once when the variable is unset, so a stray `NODE_OPTIONS` records nothing.

`scripts/tests/test_owned_observer.py` holds all three and scans the shipped roots for the
observer's names.

## Losing nothing, measured

`observe_journey.py control` runs a known workload under the recorder and counts what happened
without it. Every launched program appends a tag to a marker file, and a loopback listener counts
each connection it accepts. The Python process launches through `Popen` and `posix_spawn`, makes raw
connects, `getaddrinfo` calls and `urllib` requests, and then starts a Node child and a Bun child.
Each child runs an ES module with named imports of the builtins, the form a bundled CLI uses. Each
makes `net.connect`, `http.get`, `fetch`, `dns.lookup`, `spawnSync` and `execFile` calls. Every
connection is sub-second. The run passes only when three checks agree exactly: the trace's events
by source, kind and operation, with no extra and no missing line; the tagged launches against the
marker; and the connections the trace witnessed against the listener's count.

On 2026-10-30, with Python 3.12.13, Node 26.12.1 and Bun 1.4.4 and the default count of 20, the
trace held 511 of 511 expected events. All 120 programs that ran were recorded, and so were all 160
connections the listener accepted. The workload took 2.2 seconds. The unit test runs the same
control at a count of 12, with each runtime it finds on PATH.

The control taught the expectations two things about the runtimes:

- Bun's `fetch` is native. It never reaches `net.Socket`, so a Bun `fetch` is one `request`
  line and no `connect` line, and the control counts it as its own connection. Bun's `http` does
  reach `net.Socket`, as Node's does.
- A request is not a connection. The control's listener closes after each answer. A real
  vendor keeps connections alive, so in a journey trace several requests can share one connection.
  The report counts requests and connects separately and does not assume the two match.

## What it cannot see

- Codex 0.165.0 is a native executable. So are `git`, `gh`, `glab`, `tmux`,
  `osascript` and `spacedock`. The trace records each one's launch, arguments, pid and duration from
  the server side, and nothing it does inside. The report lists them under `opaque_launches`. Both
  vendor CLIs are signed with the hardened runtime, so library interposition is not an option, and
  it was not tried.
- Inside a Node or Bun program, a connection made by native code rather than
  through the JavaScript API is invisible: an addon, Bun's own DNS lookup for `fetch`, or anything
  the runtime does before the preload loads. The same goes for a `node:dgram` UDP socket, which is
  not wrapped. For a Bun `fetch`, the trace shows the destination host and port and not the resolved
  address.
- A program that clears `NODE_OPTIONS` or `BUN_OPTIONS` for
  its own children takes them out of view. On the server side each launch records `hooked`, which
  says whether the child's environment still carries the trace. A Python child is never hooked,
  because only `exec` installs the audit hook.
- Nothing outside the tree is seen, by design. A harness's own hooks posting to Compass run in
  the harness's tree, not the server's. The trace records only what the tree starts and connects
  to, so it shows neither those processes nor the server accepting their connections.
- No words are kept. An argument longer than 64 characters, or one that holds a newline, is recorded as
  `<N chars>`. A reading call's system prompt is an argument and its session text goes in on stdin,
  so neither reaches the trace. Socket paths are shortened the same way. Hosts, ports and short
  flags such as the model id are kept, because the report needs them.

The recorder also changes what it watches in one small way: every Node or Bun child loads one extra
file at start. A program that refuses to start with a preload would show that as a failed launch.

## Driving the five runs

`observe_journey.py run --mode MODE` starts this checkout's `server.py` under the recorder on a spare
loopback port. It gives the server a fresh `COMPASS_HOME` under the output directory, so no stored
grant, pause or summary setting carries over from another run. `HOME` stays yours unless `--home`
names another, because the journey reads real sessions and the CLIs read their own sign-in. The run
ends at Ctrl-C, after `--seconds`, or when the server exits. The runner then stops the server's
process group, lists any child still running (it does not kill them, because a pid read from a
trace may already belong to something else), and writes `report.json` and `report.md` beside
`trace.jsonl`. `--transcript PATH`, which can be repeated, records whether the session file's earlier
bytes survived and how many lines were appended, as sizes and digests only. `--clipboard` saves the
clipboard to `clipboard.txt` after the stop. Flags after `--` go to the server.

Opening a finished session starts its summary without a prior question, so the order of steps
matters in the runs that must start no model.

| Mode | Server flags | Steps | Claude calls |
|---|---|---|---|
| `default` | none | Open a finished Claude Code session, which runs its summary. Press Analyze once and copy the correction. | 2: a summary and a reading |
| `monitor-only` | none | Open a live Claude Code session, which gets no summary. Switch on the Live monitor and keep the tab visible for about three minutes. | About 3 Haiku checks, plus the live session's own turns |
| `no-model` | `--no-observer-model` | Open a finished session and press Analyze. Both the summary and the press are refused. | 0 |
| `declined` | none | Press Pause model calls before opening any session. Then open a finished session and press Analyze. Both are refused. | 0 |
| `launch-granted` | `--allow-tool-output` | The default run's steps. | 2 |

That comes to about seven calls Compass makes. Add the turns of the session the Live monitor
watches, and the total is close to the ten-turn allowance the capture was costed at.
`--allow-tool-output` is accepted and does nothing for one release ([The launch grant for tool
output](../SECURITY.md#the-launch-grant-for-tool-output)), so the launch-granted run should match the
default run line for line. A difference would be a finding.

The report attributes each event to a row of the two SECURITY.md tables by program name or vendor
host. Every row name it uses is read from SECURITY.md, and a test fails when one stops matching. The
report lists anything it cannot attribute under "Not in the table". A loopback or configured reach
connection stays there for a person to read, because the host alone does not say which row it
belongs to. Events from inside a model CLI's own tree are attributed to the reading row, or the Live
monitor row in `monitor-only`. These are the connections the tests above could never see. A departure is
something the run's own switches forbid: any model launch in `no-model` or `declined`, a model
launch without a Haiku id in `monitor-only`, and any Unix-domain socket connection, which is the path
a hand-off would take. The runner exits 1 when there is one.

Example, for the declined run with the vendor quota poll left on:

```bash
python3 scripts/observe_journey.py run --mode declined --clipboard \
  --transcript ~/.claude/projects/<project>/<session>.jsonl --out /tmp/journey-declined
```

`python3 scripts/observe_journey.py control` reruns the loss check on any machine, and
`python3 scripts/observe_journey.py report TRACE --mode MODE` re-reports a trace already recorded.
