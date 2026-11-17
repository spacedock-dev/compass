// Pi 0.85.1 extension UI events: docs/captures/pi owns the measured boundary.
// A close reports neither approval nor an answer. No native content is forwarded.
import {randomUUID} from "node:crypto";
import {constants} from "node:fs";
import {open} from "node:fs/promises";
import {request} from "node:http";
import {homedir} from "node:os";
import {join} from "node:path";

const HARNESS = "pi";
const EVENTS = Object.freeze({
  ui_prompt_start: "input_requested",
  ui_prompt_end: "input_resolved",
});
const KINDS = new Set(["select", "confirm", "input", "editor", "custom"]);
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const DEADLINE_MS = 500;
const MAX_PENDING = 32;

function default_home() {
  return join(homedir(), ".compass");
}

function state_home() {
  const override = process.env.COMPASS_HOME;
  return override?.trim() ? override : default_home();
}

async function capability(port) {
  const root = state_home();
  const stateFile = join(root, `compass-${port}.json`);
  let file;
  try {
    // Nonblocking open plus a regular-file check rejects a FIFO masquerading as
    // state; a bounded read also contains concurrent growth after stat.
    file = await open(stateFile,
      constants.O_RDONLY | (constants.O_NONBLOCK || 0) | (constants.O_NOFOLLOW || 0));
    const stat = await file.stat();
    if(!stat.isFile() || stat.size > 65536) return null;
    const buffer = Buffer.alloc(65537);
    const {bytesRead} = await file.read(buffer, 0, buffer.length, 0);
    if(bytesRead > 65536) return null;
    const state = JSON.parse(buffer.subarray(0, bytesRead).toString());
    const token = state?.capabilities?.[HARNESS];
    return typeof token === "string" && /^[A-Za-z0-9_-]{1,256}$/.test(token) ? token : null;
  } catch {
    return null;
  } finally {
    if(file) await file.close().catch(() => {});
  }
}

function post(port, token, event) {
  return new Promise(resolve => {
    let timer;
    const finish = () => { clearTimeout(timer); resolve(); };
    const body = JSON.stringify(event);
    const req = request({
      hostname: "127.0.0.1", port, path: `/api/events/${HARNESS}`, method: "POST",
      agent: false,
      headers: {"Content-Type": "application/json", "Content-Length": Buffer.byteLength(body),
        "X-Compass-Capability": token},
    }, res => {
      // No redirects, retries or response-body buffering; capability rotates on
      // restart and a failed one-shot report is not rehydrated into a new run.
      res.destroy();
      finish();
    });
    timer = setTimeout(() => { req.destroy(); finish(); }, DEADLINE_MS);
    req.on("error", finish);
    req.end(body);
  });
}

export default function compass(pi) {
  let rawPort = process.env.COMPASS_PORT;
  rawPort ??= "4553";
  if(!/^\d{1,5}$/.test(rawPort)) return;
  const port = Number(rawPort);
  if(port < 1 || port > 65535) return;
  const instance = randomUUID();
  let sequence = 0;
  let draining = false;
  const pending = [];

  async function drain() {
    draining = true;
    try {
      while(pending.length) {
        const event = pending.shift();
        const token = await capability(port);
        if(token) await post(port, token, event);
      }
    } catch {
      // Reporting failure cannot reject Pi's awaited extension callback.
      pending.length = 0;
    } finally {
      draining = false;
    }
  }

  function observe(event, ctx) {
    try {
      if(!event || event.reason !== "ui_prompt" || !KINDS.has(event.kind)) return;
      const name = EVENTS[event.type];
      const sid = ctx.sessionManager.getSessionId();
      if(!name || typeof sid !== "string" || !UUID.test(sid)) return;
      // One in-flight report, at most one queued state per session. Coalescing
      // superseded states keeps a quick close/start from clearing the later wait
      // and bounds a UI-event burst without retaining the user's native payload.
      const prior = pending.findIndex(item => item.session_id === sid);
      if(prior >= 0) pending.splice(prior, 1);
      if(pending.length >= MAX_PENDING) pending.shift();
      pending.push({v: 1, event: name, session_id: sid,
        timestamp: new Date().toISOString(), source_instance_id: instance,
        source_sequence: ++sequence});
      if(!draining) void drain();
    } catch {
      // A stale extension context is an unavailable observation, not a UI error.
    }
  }

  pi.on("ui_prompt_start", observe);
  pi.on("ui_prompt_end", observe);
}
