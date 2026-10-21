import { resumeModelCalls, turnOffReadings } from '../api/readings';
import { nextNumber } from '../api/bootstrap';
import { compatSessKey } from '../api/identity';
import type { ReadingRequest, SessionIdentity } from '../api/types';
import { annotationOf } from '../intent/annotation';
import {
  announce,
  answered,
  identityOf,
  liveRow,
  pendingEnd,
  pendingHas,
  pendingStart,
  readInput,
  refresh,
} from '../intent/context';
import { intentKey } from '../intent/derive';
import { intentForReading } from '../intent/api';
import { KEEP_REFUSED } from '../intent/sentences';
import { isRecord, type Row } from '../observed';
import { acknowledgeFlip } from './flip';
import { requestFocus } from './focus';
import { currentPayload, showJob, showReading, showRoute } from './overlay';
import {
  policyReason,
  pressRefusal,
  promptReadingRefusal,
  readingJob,
  readingRoute,
  routeRefusal,
} from './route';
import {
  CANCEL_FAILED,
  DESTINATION_CHANGED,
  PROVIDER_CHANGED,
  RESULT_MARK_UNSAVED,
  PAGE_OUTDATED,
} from './sentences';
import type { DriftCtx } from './state';
import { pressLine } from './route';
import { noticeAnnouncement } from './notice';

/* Every request the Drift section sends, each from one explicit press of one control. A mount, a second
   mount under StrictMode, a board refresh, a poll, a reconnect or a retry reaches none of them, and a lost
   answer is never retried: it does not establish that the model never ran.

   `press: true` is the shape contract's "asserted rather than assumed" made mechanical: the literal appears
   in this one place, inside a handler a click reaches, and the route refuses a body without it.
   `observer_model: 1` preserves the route's explicit-request guard, and the server checks its durable pause and
   budget again at the model seam. */

function pressDetails(ctx: DriftCtx, identity: SessionIdentity) {
  const session = liveRow(ctx.intent, identity);
  const input = session ? readInput(ctx.intent, identity, session) : null;
  const payload = currentPayload(ctx);
  if (!session || !input || !payload) return null;
  return { session, input: { ...input, payload }, payload };
}

/* What the card the reader pressed on was drawn from. The Drift card can be held while a board arrives, and
   then the board a handler reads is newer than the card the reader read: a press names what the reader saw,
   and where the two differ it sends nothing. */
export interface Drawn {
  readonly route: Row | null;
  readonly revision: number;
}

/* The sentence for a receiver that moved between the draw and the press, or nothing where it did not. The
   provider and the model say who reads it. */
function movedSince(drawn: Row | null, live: Row | null): string {
  if (!drawn || !live) return drawn === live ? '' : PROVIDER_CHANGED;
  const differs = (field: string): boolean =>
    String(drawn[field] || '') !== String(live[field] || '');
  if (differs('provider') || differs('model') || differs('harness')) return PROVIDER_CHANGED;
  return '';
}

/* One reading, on one press, and no retry. */
export async function askForReading(
  ctx: DriftCtx,
  identity: SessionIdentity,
  drawn: Drawn,
): Promise<void> {
  const { intent, shell } = ctx;
  const held = intent.held;
  const read = pressDetails(ctx, identity);
  if (!read) return;
  const { session, input, payload } = read;
  const key = compatSessKey(session);
  /* A press in flight, or a running job, is the answer to a second press: nothing is sent. */
  if (
    pendingHas(intent, `reading:${key}`) ||
    held.requests.get(key)?.pending ||
    readingJob(payload, session)
  ) {
    return;
  }
  shell.announcer.forget(`keep:${key}`);
  /* This press arrives from states the browser used to swallow, and an ungated one spends the reader's own
     model capacity from a state the page calls unavailable. Answered rather than dropped, because a
     clicked control that goes silent is indistinguishable from a dead one. */
  const request = held.requests.get(key);
  const now = shell.clock.now();
  const refusal = promptReadingRefusal({
    input,
    saving: pendingHas(intent, `${intentKey(session)}:save`),
    answered: request,
    nowMs: now,
  });
  if (refusal) {
    // A press during a held close learns the board's state; the card shows it now.
    if (refusal === pressRefusal(session, request, now)) acknowledgeFlip(ctx, session, false);
    held.requests.set(key, { ...request, pending: false, message: refusal, refusal: true });
    held.notify();
    return;
  }
  /* The receiver and the revision the card showed, sent with the press so the server can refuse one that
     changed since. A refusal above already covers a route with no provider; where the live board no longer
     agrees with the card, nothing is sent and the card's own sentence says why. */
  const live = readingRoute(payload, session);
  const route = drawn.route;
  if (!route || !live) return;
  const liveRevision = nextNumber(annotationOf(session)?.['revision']) || 0;
  const moved = movedSince(route, live) || (liveRevision !== drawn.revision ? KEEP_REFUSED : '');
  if (moved) {
    held.requests.set(key, { ...request, pending: false, message: moved });
    if (moved === KEEP_REFUSED) {
      /* Said once, by the persistent region, as the server's own revision refusal is. */
      held.requests.set(key, { ...request, pending: false, message: moved, announced: true });
      announce(intent, `keep:${key}`, moved);
    }
    held.notify();
    return;
  }
  const provider = String(route['provider']);
  const reading = intentForReading(shell, identity);
  const adoption = reading?.adoption ?? {};
  /* The revision this panel drew, so a press from a page another tab has since moved on is refused before
     anything starts: the model would otherwise read words this reader never saw. */
  const expected = drawn.revision;
  const control = `reading:${key}`;
  const press = pendingStart(intent, control, 'Starting…', 'Starting the analysis.');
  if (!press) return;
  const note: Record<string, unknown> & { pending: boolean; message: string } = {
    ...(request?.notice !== undefined ? { notice: request.notice } : {}),
    pending: true,
    message: '',
    adoption,
  };
  held.requests.set(key, note);
  held.notify();
  try {
    const body: Record<string, unknown> = {
      harness: identity.harness,
      sid: identity.sid,
      provider,
      press: true,
      observer_model: 1,
      ...adoption,
      expected_revision: expected,
      ...(provider === 'claude' ? { model: String(route['model'] || '') } : {}),
    };
    const reply = answered(
      await shell.runtime.client.postReading(body as unknown as ReadingRequest, press.signal),
    );
    if (reply.kind === 'lost') throw new Error('reading not confirmed');
    const answer: Row | null = reply.body as Row | null;
    const status = reply.status;
    if (isRecord(answer?.['route'])) {
      /* The server's route for this harness now. Kept before the refresh so the sentence below and the
         disclosure it points at agree at once. */
      showRoute(ctx, String(session['harness'] || ''), answer['route']);
    }
    if (status === 409 && isRecord(answer?.['job'])) {
      /* Another tab, or an earlier press, already started one: show it, then take the board's word for
         whether it is still running. */
      showJob(ctx, key, answer['job']);
      pendingEnd(intent, control, press);
      held.notify();
      await refresh(intent);
      return;
    }
    if (status === 409 && answer?.['reason'] === 'provider-changed') {
      note.message = PROVIDER_CHANGED;
      await refresh(intent);
      return;
    }
    if (status === 409 && answer?.['reason'] === 'revision-changed') {
      /* Nothing was started, adopted or allowed. The owner's stale sentence, shared with Keep: the next press
         is the reader's, against the words the refresh now draws. */
      note.message = KEEP_REFUSED;
      /* Said once, by the persistent region, as Keep's is and under Keep's key, which the next press
         empties: a status paragraph inside the page was re-inserted and re-read on every render. */
      note['announced'] = true;
      announce(intent, `keep:${key}`, KEEP_REFUSED);
      await refresh(intent);
      return;
    }
    if (status === 400 && answer?.['reason'] === 'page-outdated') {
      note.message = PAGE_OUTDATED;
      return;
    }
    if (status === 409 && answer?.['reason'] === 'destination-changed') {
      note.message = DESTINATION_CHANGED;
      await refresh(intent);
      return;
    }
    if (status === 409) {
      note.message =
        'A reading is already in progress for this session. Wait for it to finish; this press did not start another.';
      return;
    }
    if (isRecord(answer?.['route']) && !answer['route']['provider']) {
      const now2 = currentPayload(ctx) ?? payload;
      note.message = routeRefusal(now2, session);
      note['refusal'] = true;
      return;
    }
    if (answer?.['reason'] === 'withheld' && typeof answer['withheld'] === 'string') {
      /* Refused before any job: nothing started and nothing was spent. Held as this press's answer until the
         board publishes the row's own eligibility, which then wins, so the inert line stands beside the
         button now rather than after the next poll. */
      const eligibility = {
        ok: false,
        reason: answer['withheld'],
        until: nextNumber(answer['until']),
        sentence: String(answer['sentence'] || ''),
      };
      note['eligibility'] = eligibility;
      note.message = pressLine(session, eligibility);
      acknowledgeFlip(ctx, session, false);
      note['refusal'] = true;
      await refresh(intent);
      return;
    }
    if (answer?.['adoption_refused']) {
      note.message =
        'The prompt or saved goal changed. Review the current goal before analyzing again.';
      await refresh(intent);
      return;
    }
    if (isRecord(answer?.['reading'])) {
      showReading(ctx, answer['reading']);
      note.message = policyReason(answer['reading']);
      note['refusal'] = Boolean(note.message);
      return;
    }
    if (!reply.ok) throw new Error(`HTTP ${String(status)}`);
    const started = answer?.['ok'] === true && isRecord(answer['job']);
    if (!started && (answer?.['ok'] !== true || typeof answer['produced'] !== 'boolean')) {
      throw new Error('reading not confirmed');
    }
    note['notice'] = isRecord(answer?.['notice']) ? answer['notice'] : null;
    sayNotice(shell, note['notice']);
    if (started && answer && isRecord(answer['job'])) {
      /* Drawn now from the reply, then replaced by the board: a job can end before its own reply arrives,
         and a merged job the board has dropped would stand until the next poll and swallow every press.
         Every later phase and the result arrive with the revisions the job publishes. */
      showJob(ctx, key, answer['job']);
      // The box is the answer from here on, so the press stops being busy.
      pendingEnd(intent, control, press);
      held.notify();
      await refresh(intent);
      return;
    }
    /* Answered without a job: no annotated session by that name. */
    note.message = 'No new reading was produced.';
    await refresh(intent);
  } catch {
    /* A lost response does not establish that the model never ran. */
    note.message =
      'Could not confirm the reading. The request has not been retried. Refresh to check for a result before asking again.';
  } finally {
    note.pending = false;
    pendingEnd(intent, control, press);
    requestFocus(ctx, `reading:${key}`);
  }
}

/* Cancel the running analysis this box shows. The job id goes with it, so a stale tab cannot cancel a newer
   press. One request per job: a Cancel in flight, or one the server already accepted, sends nothing. A `409
   not-running` means the job ended or was never this one, and the board says what stands, with no sentence of
   this page's own. */
export async function cancelReading(ctx: DriftCtx, identity: SessionIdentity): Promise<void> {
  const { intent, shell, drift } = ctx;
  const read = pressDetails(ctx, identity);
  if (!read) return;
  const { session, payload } = read;
  const key = compatSessKey(session);
  const job = readingJob(payload, session);
  const held = drift.cancels.get(key);
  if (!job || job['cancelling'] === true || (held && held.job === job['id'] && held.pending))
    return;
  const control = `reading-cancel:${key}`;
  const press = pendingStart(intent, control, 'Cancelling…', 'Cancelling the analysis.');
  if (!press) return;
  const cancel = { job: String(job['id']), pending: true, failed: false };
  drift.cancels.set(key, cancel);
  drift.notify();
  try {
    const reply = answered(
      await shell.runtime.client.postReadingCancel(
        { ...identity, job: cancel.job, press: true, observer_model: 1 },
        press.signal,
      ),
    );
    if (reply.kind === 'lost') throw new Error('cancel not confirmed');
    const answer = reply.body as Row | null;
    if (reply.status === 409 && answer?.['reason'] === 'not-running') {
      pendingEnd(intent, control, press);
      drift.cancels.delete(key);
      await refresh(intent);
      return;
    }
    if (reply.status !== 202 || !answer || answer['cancelling'] !== true) {
      throw new Error('cancel not confirmed');
    }
    // Accepted: the published `cancelling` draws the finishing state from here.
    pendingEnd(intent, control, press);
    showJob(ctx, key, { ...job, cancelling: true });
    drift.cancels.delete(key);
    await refresh(intent);
  } catch {
    cancel.failed = true;
  } finally {
    cancel.pending = false;
    pendingEnd(intent, control, press);
    drift.notify();
    requestFocus(ctx, control);
  }
}

/* "Pause model calls": withdraws every provider's permission. The one request in this section that names no
   session, so the control is keyed on the session the reader is looking at. */
/* The notice card is not focused, so a reply that carries a new one is said once through the polite region. */
function sayNotice(shell: DriftCtx['shell'], notice: unknown): void {
  if (!isRecord(notice)) return;
  const { key, sentence } = noticeAnnouncement(notice);
  shell.announcer.announce(key, sentence);
}

export async function readingOff(ctx: DriftCtx, identity: SessionIdentity | null): Promise<void> {
  return setModelPause(ctx, identity, true);
}

export async function readingOn(ctx: DriftCtx, identity: SessionIdentity | null): Promise<void> {
  return setModelPause(ctx, identity, false);
}

async function setModelPause(
  ctx: DriftCtx,
  identity: SessionIdentity | null,
  paused: boolean,
): Promise<void> {
  const { intent, shell } = ctx;
  const key = identity ? compatSessKey(identity) : '';
  const action = paused ? 'reading-off' : 'reading-on';
  const control = key ? `${action}:${key}` : action;
  const press = pendingStart(
    intent,
    control,
    paused ? 'Pausing…' : 'Resuming…',
    paused ? 'Pausing model calls.' : 'Resuming model calls.',
  );
  if (!press) return;
  intent.held.notify();
  try {
    const reply = answered(
      await (paused ? turnOffReadings : resumeModelCalls)(shell.runtime.client, press.signal),
    );
    const answer = reply.kind === 'answered' && reply.ok ? (reply.body as Row | null) : null;
    if (!answer || answer['ok'] !== true || !isRecord(answer['reading'])) {
      throw new Error('permission not saved');
    }
    showReading(ctx, answer['reading']);
    for (const [name, note] of [...intent.held.requests]) {
      if (!note.pending) intent.held.requests.delete(name);
    }
    await refresh(intent);
  } catch {
    if (key) {
      intent.held.requests.set(key, {
        ...intent.held.requests.get(key),
        message: paused
          ? 'Could not confirm model calls are paused. Try pausing again.'
          : 'Could not confirm model calls resumed. Try resuming again.',
      });
    }
  } finally {
    pendingEnd(intent, control, press);
    requestFocus(ctx, control);
  }
}

/* The reader's answer, posted to the same route their words go to, with the reading's time so a newer one is
   never marked by a tab drawn before it. Pressed again it takes the mark back. It is never sent anywhere
   else and never counted. The mark and its pressed state derive from the payload, never from this press: a
   store that did not take it draws unmarked and says so. */
export async function markNotAccurate(
  ctx: DriftCtx,
  identity: SessionIdentity,
  readAt: number,
  /** Whether the card drew the reading marked: the press toggles what the reader saw. */
  marked: boolean,
): Promise<void> {
  const { intent, shell, drift } = ctx;
  const session = liveRow(intent, identity);
  if (!session) return;
  const key = compatSessKey(session);
  const control = `not-accurate:${key}`;
  const press = pendingStart(intent, control, 'Saving…');
  if (!press) return;
  intent.held.notify();
  const on = !marked;
  drift.notAccurate.delete(key);
  // Taking the mark back takes the choice with it: it described a reading the reader no longer disowns.
  if (marked) drift.wrong.delete(key);
  let saved = false;
  try {
    const reply = answered(
      await shell.runtime.client.postAnnotate(
        { ...identity, not_accurate: on, read_at: readAt },
        press.signal,
      ),
    );
    const body = reply.kind === 'answered' && reply.ok ? (reply.body as Row | null) : null;
    saved = Boolean(
      body &&
        body['persisted'] !== false &&
        ['stored', 'unchanged'].includes(String(body['outcome'] || '')),
    );
  } catch {
    saved = false;
  }
  if (!saved) drift.notAccurate.add(key);
  try {
    await refresh(intent);
  } finally {
    pendingEnd(intent, control, press);
    drift.notify();
    requestFocus(ctx, control);
  }
}

export { CANCEL_FAILED, RESULT_MARK_UNSAVED, identityOf };
