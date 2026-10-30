# The owned-process observer

SECURITY.md's [What launches and what sends](../SECURITY.md#what-launches-and-what-sends) pins every
outbound and launch path by test, against Compass's own code with the leaving call patched. Those
tests stop at the gate. Once Compass has started the Claude Code or Codex CLI, they cannot see what
that program connects to. They also miss a connection a dependency makes below the patched call, and
they cannot say which process did what. [What the tests do not see, and what a live capture would
add](../SECURITY.md#what-the-tests-do-not-see-and-what-a-live-capture-would-add) names the live
capture that would close the gap. This record covers the recorder that capture needs. It describes
what the recorder sees and what it cannot, and how to drive the journey runs with it.

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
  and its exit, so a launch has a duration. Another records the route of each POST the server
  answers, because a press is a POST and the report uses it to tell Find goal from Analyze.
- `exec` also puts `NODE_OPTIONS=--require=…/owned_observer_preload.js` and
  `BUN_OPTIONS=--preload=…` on the server's environment. Both variables are inherited, so each Node
  or Bun program in the tree loads the preload before its own code and hands it on to its children.
  The preload wraps `net.Socket.prototype.connect` (every Node TCP and TLS client, `http`, `https`
  and `fetch` included), `http`/`https` `request` and `get`, `fetch` and `Bun.fetch`, `WebSocket`,
  `Bun.connect`, `dns.lookup`, the `child_process` launchers, and `Bun.spawn`. It records start and
  exit too.

Both sides write synchronously to one append-only file, and they write before the recorded call
runs. A connection that lasts a millisecond still gets its line. That is the property sampling
lacked. The log's path must be absolute, so every process in the tree writes to the same file
whatever its working directory; `exec` refuses a relative one, and the preload ignores it.

`BUN_OPTIONS` was not optional. Claude Code 2.1.314 is a Bun 1.4.4 executable, measured by loading a
marker preload under `claude --version`. It ignores `NODE_OPTIONS=--require` and loads a preload
named in `BUN_OPTIONS`. Without that variable the reading model's own requests would be invisible.

## It is off unless asked

- `exec` refuses with exit status 2, and runs nothing, unless `COMPASS_OBSERVE_LOG` names an
  absolute path.
- `server.py` started the ordinary way never reads that variable, even when it is set, because the
  hook is installed by `exec` and nothing in `compass_runtime` imports the observer.
- The preload returns at once when the variable is unset or relative, so a stray `NODE_OPTIONS`
  records nothing.

`scripts/tests/test_owned_observer.py` holds all three and scans the shipped roots for the
observer's names.

## What a line keeps

A launch line keeps the program's file name, every flag name, and three kinds of value: the value
after a flag Compass passes from its own code (`--model`, `--effort`, `--output-format`,
`--permission-mode`, `--permission-prompts`, `--tools`, `--sandbox`, `--config`), a word of a command
Compass starts for itself (`rev-parse`, `checks`, `list-clients` and the like), and, for
`--system-prompt`, its length and the first twelve hex digits of its SHA-256. The prompt is a
constant in Compass's code, and the digest is how the report tells a reading from a summary or a
Live monitor check. Every other value is recorded as `<N chars>`, so `--token abc123` becomes
`--token <6 chars>` and a path becomes its length. A reading call's session text goes in on stdin and
never reaches the trace. Both sides apply the same lists, and a test holds the preload's copy to the
Python one.

A connect line keeps the host and port, or `<N chars>` for a Unix socket's path. A request line keeps
scheme, host and port, never a path or query, so a reach URL's secret part stays out.

## Losing nothing, measured

`observe_journey.py control` runs a known workload under the recorder and counts what happened
without it. Every launched program appends a tag to a marker file, and a loopback listener counts
each connection it accepts. The Python process launches through `Popen` and `posix_spawn`, makes raw
connects, `getaddrinfo` calls and `urllib` requests, then makes a connect and a launch from each of
`count` threads at once, and then starts a Node child and a Bun child. Each child runs an ES module
with named imports of the builtins, the form a bundled CLI uses. Each makes `net.connect`,
`http.get`, `fetch`, `dns.lookup`, `spawnSync` and `execFile` calls in turn, and then `count`
connects and `count` spawns all in flight together. Every connection is sub-second.

The run passes only when three checks hold. The trace's events by source, kind and operation match
the expected counts exactly, with no extra and no missing line. The tagged launches match the marker.
The connections the trace witnessed are at least the listener's count. That last check is "at
least" because a line is an attempt, written before the call runs: a refused or reset connect is
still a line, so under a full listen queue the trace holds more connects than were accepted. Only
fewer would mean a lost event.

On 2026-10-30, with Python 3.12.13, Node 26.12.1 and Bun 1.4.4 and the default count of 20, the
trace held 671 of 671 expected events. All 180 programs that ran were recorded, and so were all 220
connections the listener accepted. The workload took 1.5 seconds. The unit test runs the same
control at a count of 12, with each runtime it finds on PATH.

The control taught the expectations two things about the runtimes:

- Bun's `fetch` is native. It never reaches `net.Socket`, so a Bun `fetch` is one `request`
  line and no `connect` line, and the control counts it as its own connection. Bun's `http` does
  reach `net.Socket`, as Node's does.
- A request is not a connection. The control's listener closes after each answer. A real
  vendor keeps connections alive, so in a journey trace several requests can share one connection.
  The report counts requests and connects separately and does not assume the two match.

## What it cannot see

- Codex 0.165.0 is a native executable. So are `git`, `gh`, `glab`, `tmux`, `osascript`, `ps`,
  `security` and `spacedock`. The trace records each one's launch, its kept arguments, pid and
  duration from the server side, and nothing it does inside. The report lists them under "Seen
  only from outside". Both vendor CLIs are signed with the hardened runtime, so library
  interposition is not an option, and it was not tried.
- Inside a Node or Bun program, a connection made by native code rather than through the
  JavaScript API is invisible: an addon, Bun's own DNS lookup for `fetch`, or anything the runtime
  does before the preload loads. A `node:dgram` UDP socket, `dns.resolve*` and `dns.Resolver`, and
  a `ChildProcess` built with `new` and started with its own `spawn()` are not wrapped either. For a
  Bun `fetch`, the trace shows the destination host and port and not the resolved address.
- Bun has two more ways out, both measured by the soundness review on Bun 1.4.4. A `Bun.$` shell
  command ran and left no launch line. A Bun `Worker` does not load the preload, so a launch and a
  connect made inside one ran and were not recorded. Claude Code is a Bun program, so either would
  hide part of its work.
- On the Python side, `multiprocessing` with the spawn or forkserver start method,
  `multiprocessing.util.spawnv_passfds` and `os.forkpty` start programs without an audited launch
  event, and `socket.sendmsg` sends without one. `compass_runtime` uses none of them today.
- A program that clears `NODE_OPTIONS` or `BUN_OPTIONS` for its own children takes them out of
  view. On the server side each launch records `hooked`, which says whether the child's environment
  still names the log and the preload. The Node and Bun side records no such field, so a grandchild
  started with a cleared environment leaves no trace at all. A Python child is never hooked, because
  only `exec` installs the audit hook.
- Nothing outside the tree is seen, by design. A harness's own hooks posting to Compass run in the
  harness's tree, not the server's. The trace records only what the tree starts and connects to, so
  it shows neither those processes nor the server accepting their connections.

The recorder also changes what it watches in one small way: every Node or Bun child loads one extra
file at start. A program that refuses to start with a preload would show that as a failed launch.

## Driving the runs

`observe_journey.py run --mode MODE` starts this checkout's `server.py` under the recorder on a spare
loopback port. It gives the server a fresh `COMPASS_HOME` under the output directory, so no stored
grant, pause or summary setting carries over from another run. `HOME` stays yours unless `--home`
names another, because the journey reads real sessions and the CLIs read their own sign-in. Flags
after `--` go to the server; `--daemon` is refused, because a server that forks away leaves the
runner's process group and its trace goes on growing after the report is written.

Each mode carries a Claude call budget. The runner passes it to the hook, which counts every launch
of `claude` or `codex` and refuses the one past the budget with `PermissionError` before the program
starts, writing a `refused` line. The runner watches the trace and stops the server at the first
refusal. A run therefore cannot spend more than its budget, whatever the session turns out to hold.

The budgets have to be right, because a session summary is not one call. It is one call per 16 KiB
window of the session, plus a closing call, and a fresh store summarizes a finished session again on
every run. The default run needs a finished session short enough for one window (2 calls), and the
other runs that make calls store Turn off summaries in their fresh store before the server starts.

The run ends at Ctrl-C, after `--seconds` (or the mode's own limit), when the server exits, or at a
refusal. The runner then stops the server's process group and lists any child still running. It does
not kill them, because a pid read from a trace may already belong to something else. It writes
`report.json` and `report.md`, which carry arguments and paths and are readable by their owner only,
and `report-shapes.md`, which carries no argument, path or user name and is the one to attach to an
issue or quote in SECURITY.md. `--transcript PATH`, which can be repeated, records whether the
session file's earlier bytes survived and how many lines were appended, as sizes and digests only.
`--clipboard` puts a random sentinel on the clipboard at the start and, after the stop, keeps what is
there only if it changed, in `clipboard.txt`, readable by its owner only. Use it only in a run that
copies something; it replaces whatever was on the clipboard before.

| Run | Mode | Server flags | Summaries | Steps | Claude call budget |
|---|---|---|---|---|---|
| 0 | `no-model` | `--no-observer-model` | on | A rehearsal of every step below on the same build: open a finished session, press Analyze, Find goal and the Live monitor switch. All are refused. It also shows whether the spare-port server treats a live session as live, since the harness hooks post to your usual port. | 0 |
| 1 | `no-model` | `--no-observer-model` | on | The same steps, recorded. | 0 |
| 2 | `paused` | none | on | Press Pause model calls before opening any session. Then open a finished session and press Analyze, Find goal and the Live monitor switch. All are refused. | 0 |
| 3 | `default` | none | on | Open a finished Claude Code session short enough for one summary window, with a pull request so `gh` runs (summary: 2 calls). Press Analyze once (1 call). Copy the correction; use `--clipboard` and `--transcript`. | 3 |
| 4 | `monitor-only` | none | off | Open a session that is live now and switch on the Live monitor. Keep the tab visible and press nothing else. The run ends after 150 seconds. | 3 |
| 5 | `launch-granted` | `--allow-tool-output` | off | Open a finished session and press Analyze once. | 1 |

The budgets total 7 calls. `--allow-tool-output` is accepted and does nothing for one release ([The
launch grant for tool output](../SECURITY.md#the-launch-grant-for-tool-output)), so run 5's reading
call should match run 3's argument for argument. A difference would be a finding.

The report attributes each event to a row of the two SECURITY.md tables, and every row name it uses
is read from SECURITY.md, so a test fails when one stops matching. A model launch is placed by its
own arguments. The system prompt's digest names a reading, a summary or a Live monitor check.
Analyze, an unasked check and Find goal share the reading envelope, so the route of the POST answered
just before the launch tells Find goal from the other two. `git` goes to the git probe, `gh` and
`glab` to the CI read, `security` to the quota poll's credential read, `ps` to the process-group
check, `osascript` to the native notification, and `tmux` to the read-only terminal when it attaches
and to the focus command otherwise. The vendor quota hosts go to the quota row, and the reach
endpoint, when `--reach-url` or `COMPASS_REACH_URL` names one, to the reach row. Events from inside a
model CLI's own tree go to the row of the call that started it. These are the connections the tests
above could never see.

Anything the report cannot attribute is listed under "Not in the table". A loopback connection stays
there for a person to read, because the host alone does not say which row it belongs to. A
departure is something the run's own switches forbid: any model launch in `no-model` or `paused`, a
model launch other than a Live monitor check in `monitor-only`, a launch refused past the budget, and
any Unix-domain socket connection, which is the path a hand-off would take. The runner exits 1 when
there is one.

Example, for run 3:

```bash
python3 scripts/observe_journey.py run --mode default --clipboard \
  --transcript ~/.claude/projects/<project>/<session>.jsonl --out /tmp/journey-default
```

`python3 scripts/observe_journey.py control` reruns the loss check on any machine, and
`python3 scripts/observe_journey.py report TRACE --mode MODE` re-reports a trace already recorded.
