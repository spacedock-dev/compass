import { nextNumber } from '../api/bootstrap';
import { compatSessKey } from '../api/identity';
import {
  annotationDiscarded,
  annotationLines,
  storeUnreadable,
  annotateOn,
  type Annotation,
} from '../intent/annotation';
import { editedRefusal, intentDraft, intentUnsaved, type DraftInput } from '../intent/derive';
import { isRecord, type Row } from '../observed';
import { formatDuration } from '../shell/format';
import { openedWithControl, promptCandidate } from '../sessions/intent';
import {
  ANNOTATIONS_OFF,
  MODEL_OFF,
  READINGS_OFF,
  MODEL_UNREAD,
  NO_WORDS,
  PRESS_CLAUDE,
  PRESS_CODEX,
  PRESS_EVENTS,
  PRESS_LINES,
  ROUTE_UNREAD,
  SAVE_STEP,
  UNAUTHORIZED,
} from './sentences';

/* Who would read a session, whether readings are on, and what refuses a press before it is made. Every
   function reads the payload it is given and nothing else, so the refusal the control draws and the one the
   handler enforces come from one derivation: a handler with a second opinion can refuse a press the button
   offered, or take one it refused. The legacy cockpit's `nextReading*` functions are the oracle. */

/* The page's one duration spelling, with the zero a caller wants in a sentence. */
export const fmtDur = (seconds: number): string => formatDuration(seconds) ?? '0s';

export function readingRoute(payload: Row, session: Row | null | undefined): Row | null {
  const routes = payload['reading_routes'];
  const route =
    isRecord(routes) && session ? (routes as Row)[String(session['harness'] || '')] : null;
  return isRecord(route) ? route : null;
}

export function readingsOff(payload: Row): boolean {
  const policy = payload['reading'];
  return isRecord(policy) && (policy['off'] === true || policy['reason'] === 'model-calls-paused');
}

export function readingsOn(payload: Row): boolean {
  const policy = payload['reading'];
  return isRecord(policy) && policy['consent'] === true && !readingsOff(payload);
}

/* Whether a press could read this row now, as the board published it, or as this tab's last press was
   answered when the board has not published it. Absent means not computed, and a press is then offered and
   the server decides. A settling row whose `until` has passed is read as eligible on the next render or
   press, with no timer of its own: the next collection drops the token anyway. */
export function eligibility(
  session: Row,
  answered: Readonly<Record<string, unknown>> | undefined,
  nowMs: number,
): Row | null {
  const published = session['reading_eligibility'];
  const given = answered?.['eligibility'];
  const held = isRecord(published) ? published : isRecord(given) ? given : null;
  if (!held || held['ok'] !== false || typeof held['reason'] !== 'string') return null;
  const until = nextNumber(held['until']);
  if (until !== null && nowMs / 1000 >= until) return null;
  return held;
}

/* The short line beside an inert Analyze drift, one per token the board can publish as
   `reading_eligibility.reason`. Codex, which reads only while a turn runs and has no session end the board
   can observe, gets its own line for both idle tokens. No line promises Analyze opens "once this session
   finishes a turn": the turn may have finished where Compass could not see it. */
export function pressLine(session: Row | null | undefined, held: Row): string {
  const reason = String(held['reason']);
  const harness = String(session?.['harness'] || '');
  if (harness === 'codex' && ['idle-unknown', 'turn-stop'].includes(reason)) return PRESS_CODEX;
  if (reason === 'idle-unknown' && harness === 'claude') return PRESS_CLAUDE;
  if (reason === 'idle-unknown' && session && session['acquisition'] === 'event')
    return PRESS_EVENTS;
  return Object.hasOwn(PRESS_LINES, reason)
    ? (PRESS_LINES[reason] as string)
    : String(held['sentence'] || '');
}

export function pressRefusal(
  session: Row,
  answered: Readonly<Record<string, unknown>> | undefined,
  nowMs: number,
): string {
  const held = eligibility(session, answered, nowMs);
  return held ? pressLine(session, held) : '';
}

/* How long ago a stored withhold was written, for "Last analysis, 3m ago:". */
export function withheldAge(annotation: Annotation | null | undefined, generated: number): string {
  const at = nextNumber(annotation?.['reading_withheld_at']);
  if (at === null) return '';
  const age = Math.max(0, generated - at);
  return age < 60 ? 'just now' : `${fmtDur(age)} ago`;
}

export function routeRefusal(payload: Row, session: Row): string {
  const route = readingRoute(payload, session);
  if (!route) return ROUTE_UNREAD;
  return route['provider'] ? '' : String(route['note'] || ROUTE_UNREAD);
}

export function policyReason(policy: unknown, nowMs: number = Date.now()): string {
  if (!isRecord(policy)) return MODEL_UNREAD;
  /* The master pause outranks spend, while a startup refusal or unreadable store still leads.
     [Consent notice payload](../../../docs/design-session-summary.md#consent-notice-payload) */
  if (policy['reason'] === 'run-disabled') return MODEL_OFF;
  if (policy['reason'] === 'store-unavailable') {
    return 'Reading permission or its daily budget could not be read or saved. Restore access to the Compass store before analyzing drift.';
  }
  if (policy['off'] === true || policy['reason'] === 'model-calls-paused') return READINGS_OFF;
  if (policy['reason'] === 'daily-cap') {
    const at = nextNumber(policy['retry_at']);
    return at === null
      ? 'Analysis limit reached. Wait for the next update.'
      : `Analysis limit reached. You can analyze again at ${capReset(at, nowMs)}.`;
  }
  return '';
}

/* The running analysis for a session, from the published payload alone: a reload, another tab and this
   press all read the same job. */
export function readingJob(payload: Row, session: Row): Row | null {
  const jobs = payload['reading_jobs'];
  const job = isRecord(jobs) ? jobs[compatSessKey(session)] : null;
  return isRecord(job) && typeof job['id'] === 'string' ? job : null;
}

/* The analysis budget is published so a reader who has spent it can be told, and only then: under the cap
   the count is noise. Rolling, so `retry_at` is when the oldest analysis in the window ages out and one
   more may run. */
export interface ReadingCap {
  readonly limit: number;
  /** Epoch seconds, or null when the server did not publish one. */
  readonly retryAt: number | null;
}

export function readingCap(payload: Row): ReadingCap | null {
  const policy = payload['reading'];
  if (!isRecord(policy)) return null;
  const { used, limit } = policy;
  const counted =
    Number.isInteger(used) && Number.isInteger(limit) && (limit as number) > 0
      ? (used as number) >= (limit as number)
      : false;
  if (policy['reason'] !== 'daily-cap' && !counted) return null;
  return {
    limit: Number.isInteger(limit) && (limit as number) > 0 ? (limit as number) : 0,
    retryAt: nextNumber(policy['retry_at']),
  };
}

/* "09:38", or "09:38 tomorrow" when it falls on the next local day. The window is 24 hours, so it is never
   further out than that. */
export function capReset(retryAt: number, nowMs: number): string {
  const at = new Date(retryAt * 1000);
  const time = at.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  return at.toDateString() === new Date(nowMs).toDateString() ? time : `${time} tomorrow`;
}

export function capLine(cap: ReadingCap, nowMs: number): string {
  const limit = cap.limit ? `${String(cap.limit)} drift analyses` : 'drift analyses';
  const head = `You’ve reached the limit of ${limit} for the past 24 hours.`;
  return cap.retryAt === null
    ? head
    : `${head} You can analyze again at ${capReset(cap.retryAt, nowMs)}.`;
}

/* A discard record satisfies the nothing-typed arm too, and the wider answer is the less true of the two, so
   it is checked first. The sentence is the server's, so the block and the route behind its button cannot
   word one state two ways; the page adds the one step that lifts it. */
export function readingStates(payload: Row, annotation: Annotation | null | undefined): string {
  if (annotationDiscarded(annotation)) {
    const said = isRecord(payload['annotate_discard']) ? payload['annotate_discard'] : {};
    const why = String(said['unreadable'] || '').trim();
    return why ? `${why} ${SAVE_STEP}` : SAVE_STEP;
  }
  const unreadable = storeUnreadable(payload);
  if (unreadable) return unreadable;
  if (!String(annotation?.['goal'] || '').trim() && !annotationLines(annotation).length) {
    return NO_WORDS;
  }
  return policyReason(payload['reading']);
}

/* First, because with the store off there are no words to read and the route answers 503 whatever else is
   true. A stored reading outlives the model option: only the new request is gated here. */
export function readingRefusal(payload: Row, annotation: Annotation | null | undefined): string {
  if (!annotateOn(payload)) return ANNOTATIONS_OFF;
  const check = payload['reading_check'];
  const authorized = check === 'passed' || check === 'accepted';
  return readingStates(payload, annotation) || (authorized ? '' : UNAUTHORIZED);
}

export interface PromptRefusalInput {
  readonly input: DraftInput;
  /** Save intent is being answered, so telling the reader to save is false. */
  readonly saving: boolean;
  readonly answered: Readonly<Record<string, unknown>> | undefined;
  readonly nowMs: number;
}

/* The one reason an Analyze press cannot run, in rank order: annotations off, a route with no reader, a
   board that already says it cannot serve the press, an unsaved edit, then the words and the policy.
   `heldLive` skips the board's press refusal, for a card still holding a close. */
export function promptReadingRefusal(
  { input, saving, answered, nowMs }: PromptRefusalInput,
  heldLive = false,
): string {
  const { payload, session } = input;
  if (!annotateOn(payload)) return ANNOTATIONS_OFF;
  /* A route with no reader is a fact about this machine, and it outranks any step the page could name:
     saving a goal here would not let a check run. */
  const route = readingRoute(payload, session);
  if (route && !route['provider']) return routeRefusal(payload, session);
  /* So does a press the board already says it cannot serve: saving or choosing words would not let it
     read. */
  const press = heldLive ? '' : pressRefusal(session, answered, nowMs);
  if (press) return press;
  if (intentUnsaved(input)) return editedRefusal(saving);
  let annotation = input.annotation;
  if (!String(annotation?.['goal'] || '').trim()) {
    const draft = intentDraft(input);
    /* Over a control-first session the latest prompt is no goal either, so the press falls to the refusal
       for nothing typed. */
    const candidate =
      draft ?? (openedWithControl(session) ? null : promptCandidate(session, 'latest-prompt'));
    if (candidate && candidate.at === null) {
      return 'The prompt time was not published, so it cannot be adopted. Type a goal to analyze drift.';
    }
    if (candidate) {
      annotation = { ...annotation, goal: candidate.text, discarded_at: null, discarded_why: '' };
    }
  }
  return readingRefusal(payload, annotation) || routeRefusal(payload, session);
}

/* The server's own parts, unreworded in the notice and the "What is sent" popover. A route from before the parts were published shows its
   whole disclosure as one item. */
export function disclosureParts(
  route: Row | null | undefined,
  provider: string,
  disclosure: string,
): string[] {
  const parts = route?.['disclosure_parts'];
  if (provider && Array.isArray(parts) && parts.length) return parts.map(String);
  return provider && disclosure ? [disclosure] : [];
}
