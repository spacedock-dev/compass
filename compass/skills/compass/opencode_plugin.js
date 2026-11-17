// Passive, per-project OpenCode permission reporting. The host owns every answer.
// Current capture proves parent IDs only; forwarding never promotes child rows.
import {constants} from "node:fs";
import {open} from "node:fs/promises";
import {homedir} from "node:os";
import {join} from "node:path";
import {request} from "node:http";

const MAX_SESSIONS = 128;
const MAX_REQUESTS = 64;
const TIMEOUT_MS = 250;
const validSession = value => typeof value === "string" && /^ses_[A-Za-z0-9]{26}$/.test(value);
const validRequest = value => typeof value === "string" && value.length > 0 && value.length <= 256;

function default_home() {
  return join(homedir(), ".compass");
}

function state_home() {
  const override = process.env.COMPASS_HOME;
  return override?.trim() ? override : default_home();
}

async function capability(port) {
  const home = state_home();
  const stateFile = join(home, `compass-${port}.json`);
  let file;
  try {
    // A FIFO at this local path must not leave a read queued forever in the host.
    file = await open(
      stateFile,
      constants.O_RDONLY | (constants.O_NONBLOCK || 0) | (constants.O_NOFOLLOW || 0),
    );
    if (!(await file.stat()).isFile()) return null;
    const buffer = Buffer.alloc(65537);
    const {bytesRead} = await file.read(buffer, 0, buffer.length, 0);
    if (bytesRead > 65536) return null;
    const token = JSON.parse(buffer.toString("utf8", 0, bytesRead))?.capabilities?.opencode;
    return typeof token === "string" && /^[A-Za-z0-9_-]{1,256}$/.test(token) ? token : null;
  } catch {
    return null;
  } finally {
    if (file) await file.close().catch(() => {});
  }
}

async function forward(port, event) {
  // Read for every delivery: a restart rotates the capability, and no state-file
  // URL or proxy environment variable may choose the destination.
  const token = await capability(port);
  if (!token) return;
  await new Promise(resolve => {
    let req;
    const timer = setTimeout(() => {
      req?.destroy();
      resolve();
    }, TIMEOUT_MS);
    const finish = () => { clearTimeout(timer); resolve(); };
    try {
      req = request({
        hostname: "127.0.0.1", port, path: "/api/events/opencode", method: "POST",
        headers: {"Content-Type": "application/json", "X-Compass-Capability": token},
        agent: false,
      }, response => {
        // No response body is evidence, and redirects never carry the capability.
        response.destroy();
        finish();
      });
      req.on("error", finish);
      req.end(JSON.stringify(event));
    } catch {
      req?.destroy();
      finish();
    }
  });
}

export const CompassPlugin = async () => {
  let configured = process.env.COMPASS_PORT;
  configured ??= "4553";
  const port = /^\d{1,5}$/.test(configured) ? Number(configured) : 0;
  const sessions = new Map();
  const pending = new Map();
  const completed = new Set();
  let running = false;

  async function drain() {
    if (running) return;
    running = true;
    try {
      while (pending.size) {
        const [sid, event] = pending.entries().next().value;
        pending.delete(sid);
        await forward(port, {v: 1, event, session_id: sid});
      }
    } catch {
      // Observation is best effort; never throw into the host's permission path.
    } finally {
      running = false;
    }
  }

  return {event: async ({event} = {}) => {
    try {
      if (port < 1 || port > 65535) return;
      const kind = event?.type;
      if (kind !== "permission.asked" && kind !== "permission.replied") return;
      const props = event?.properties;
      const sid = props?.sessionID;
      const id = kind === "permission.asked" ? props?.id : props?.requestID;
      if (!validSession(sid) || !validRequest(id)) return;
      const key = JSON.stringify([sid, id]);
      if (completed.has(key)) return;
      let state = sessions.get(sid);
      let changed = false;
      if (kind === "permission.asked") {
        if (!state) {
          if (sessions.size + pending.size >= MAX_SESSIONS) return;
          state = {requests: new Set(), saturated: false};
          sessions.set(sid, state);
        }
        if (state.requests.has(id)) return;
        if (state.requests.size >= MAX_REQUESTS) {
          // An untracked request must never let the final tracked reply claim
          // clearance. Saturation retains the wait for this plugin lifetime.
          state.saturated = true;
          return;
        }
        changed = state.requests.size === 0;
        state.requests.add(id);
      } else {
        if (!state || !state.requests.delete(id)) return;
        completed.add(key);
        if (completed.size > MAX_SESSIONS * MAX_REQUESTS) {
          completed.delete(completed.values().next().value);
        }
        if (state.requests.size === 0 && !state.saturated) {
          changed = true;
          sessions.delete(sid);
        }
      }
      if (changed) {
        // Coalesce undelivered transitions by full session ID. At most one
        // request is in flight and one latest state is queued per tracked row.
        pending.set(sid, kind === "permission.asked" ? "input_requested" : "input_resolved");
        void drain();
      }
    } catch {
      // No payload, token, host error, or permission content is logged.
    }
  }};
};
