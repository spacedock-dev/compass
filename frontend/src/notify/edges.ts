import { isRecord, nativeSession, type Row } from '../observed';

/* The two transitions worth interrupting a reader for, and the sentences a banner is built from. Pure:
   nothing here reads the clock, the permission or the Notification API, so the rules are testable
   without a browser and a test never creates a native notification. The legacy page's `nextNotifyEdge`
   and its two banner builders, held to it by the differential test. */

export interface NotifyEdge {
  readonly title: string;
  readonly detail: string;
}

export interface Banner {
  readonly title: string;
  readonly body: string;
  readonly tag: string;
}

/* A gate is a request; a session falling quiet is not, so the two do not share a title: "is waiting on
   you" over a turn that merely stopped is a claim about intent that nothing here measured. They share the
   session's tag on purpose, so a row that goes quiet and then asks a question replaces its own banner
   rather than stacking a second one.

   WHAT THE QUIET NUDGE CAN AND CANNOT SEE. The native lane fires this off Claude's own `idle_prompt` hook
   event. The browser has no hook, only polled `state`, so this fires on the working to idle edge, which is
   the moment the row crosses `working_threshold_sec` without new activity and not the moment the harness
   declares itself idle. That is near-parity and not parity, taken deliberately: exact parity needs the
   notification kind, which the server drops for the idle types. The title says "has gone quiet", which is
   exactly what was observed, rather than borrowing the gate's stronger sentence. */
export function notifyEdge(session: Row, previous: unknown): NotifyEdge | null {
  session = nativeSession(session);
  /* Ahead of the `active` gate deliberately, and it must stay there: the idle overlay publishes
     `active:false` alongside `state:"idle"`, so gating this edge on `active` refuses the one transition it
     exists to report, on the default install, since both shipped hook manifests declare `Stop`.
     `previous === "working"` is the liveness check instead. Only from `working`: an answered question also
     lands on idle, and the reader was standing right there when it did. An idle row seen for the first
     time is not a transition either, because `previous` is undefined then.
     ([N-13](docs/design-needs-input.md#n-13)) */
  if (session['state'] === 'idle' && previous === 'working') {
    return { title: 'has gone quiet', detail: 'awaiting your message' };
  }
  if (session['active'] !== true) return null;
  if (session['state'] === 'needs_input' && previous !== 'needs_input') {
    return { title: 'is waiting on you', detail: 'needs your input' };
  }
  return null;
}

function harnessRows(payload: Row | null): Row[] {
  return payload && Array.isArray(payload['harnesses'])
    ? (payload['harnesses'] as unknown[]).filter(isRecord)
    : [];
}

/* The harness's label where the board named one, else the key. A key that matches nothing falls back to
   itself and an ask's falls back to nothing, which is why they are two readers. */
export function harnessName(payload: Row | null, key: unknown): string {
  const row = harnessRows(payload).find((harness) => harness['key'] === key);
  return String((row && row['label']) || key);
}

function askLabel(payload: Row | null, key: unknown): string {
  const row = harnessRows(payload).find((harness) => harness['key'] === key);
  return String((row && row['label']) || '');
}

export function sessionBanner(payload: Row, session: Row, edge: NotifyEdge): Banner {
  session = nativeSession(session);
  return {
    title: `${harnessName(payload, session['harness'])} ${edge.title}`,
    body: `[${String(session['project'])}] ${String(session['state_detail'] || edge.detail)}`,
    tag: `${String(session['harness'])}:${String(session['sid'])}`,
  };
}

/* One banner for however many questions arrived in one payload: a single one names its harness and its
   question, several name the count and the projects. */
export function askBanner(payload: Row, fresh: readonly Row[]): Banner {
  const first = fresh[0] as Row;
  const one = fresh.length === 1;
  const title = one
    ? `${askLabel(payload, first['harness']) || 'An agent'} is asking you`
    : `${String(fresh.length)} questions are waiting for your answer`;
  const projects = [...new Set(fresh.map((ask) => ask['project']).filter(Boolean))];
  const body = one
    ? `${String(first['question'])}${first['project'] ? ` · ${String(first['project'])}` : ''}`
    : projects.length
      ? projects.join(' · ')
      : String(first['question']);
  return { title, body, tag: one ? `compass-ask:${String(first['id'])}` : 'compass-ask' };
}
