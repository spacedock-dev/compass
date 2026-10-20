import { compatSessKey, contextKey } from '../api/identity';
import type { SessionIdentity } from '../api/types';
import { annotationOf } from '../intent/annotation';
import { answered, liveRow } from '../intent/context';
import { workSource } from '../intent/work';
import { stableProjectKey } from '../api/identity';
import { payloadSessions } from '../api/bootstrap';
import type { Row } from '../observed';
import {
  correctionParts,
  correctionStale,
  correctionStamp,
  correctionText,
  readerUtcOffset,
  type HeldCorrection,
} from './correction';
import { requestFocus } from './focus';
import { CORRECTION_FAILED, CORRECTION_NOTHING, CORRECTION_PAINT_PAUSED } from './sentences';
import type { DriftCtx } from './state';

/* Steer back: one request to compose the correction on the press that opens it, and one to record a copy of
   it. Neither writes into the session: the reader pastes the text where they choose, and Compass recognises
   it coming back as its own words. The legacy page's `nextCockpitSteerBack` and its neighbours are the
   oracle. */

/* The request is bounded as the pending registry's presses are, though no control is busy on it. */
const COMPOSE_BOUND_MS = 15_000;

function bounded(ctx: DriftCtx): { readonly signal: AbortSignal; done(): void } {
  const controller = new AbortController();
  const handle = ctx.shell.clock.setTimeout(() => controller.abort(), COMPOSE_BOUND_MS);
  return { signal: controller.signal, done: () => ctx.shell.clock.clearTimeout(handle) };
}

function sourceFor(ctx: DriftCtx, session: Row) {
  const snapshot = ctx.shell.runtime.store.getSnapshot();
  const label = String(session['project'] == null ? '' : session['project']);
  const data = snapshot.data;
  const projectKey = stableProjectKey({
    label,
    sessions: data
      ? payloadSessions(data).rows.filter((row) => String(row.project ?? '') === label)
      : [],
  });
  return workSource(
    snapshot.contexts,
    projectKey,
    session,
    snapshot.records.get(contextKey(projectKey, session as never)),
  );
}

/* What the correction's text is right now: the reader's own where they edited or copied it, the frozen text of
   a recomposition being fetched, and otherwise the server's parts as text. */
export function correctionDraft(held: HeldCorrection): string {
  if (typeof held.text === 'string') return held.text;
  if (held.recomposing && typeof held.recomposeText === 'string') return held.recomposeText;
  return correctionText(held.parts);
}

/* One request for the session's correction. `quiet` is the held entry of a recomposition the reader did not
   press for (`followCorrection`): that box stays drawn until the answer, an edit made to it meanwhile keeps it
   as the reader's, and with nothing left to steer from it closes rather than refusing a press nobody made. */
export async function composeCorrection(
  ctx: DriftCtx,
  identity: SessionIdentity,
  stamp: string,
  quiet: HeldCorrection | null = null,
): Promise<void> {
  const { drift } = ctx;
  const key = compatSessKey(identity);
  const next: HeldCorrection = {
    id: drift.nextCorrectionId(),
    open: true,
    pending: true,
    parts: null,
    text: null,
    edited: false,
    why: '',
    cue: '',
    stamp,
    cited: null,
    failed: null,
  };
  if (!quiet) {
    drift.corrections.set(key, next);
    drift.notify();
  }
  const request = bounded(ctx);
  try {
    const reply = answered(
      await ctx.shell.runtime.client.postCorrection(
        { ...identity, utc_offset_minutes: readerUtcOffset() },
        request.signal,
      ),
    );
    if (reply.kind === 'lost') throw new Error('correction not composed');
    const body = reply.body as Row | null;
    const parts = reply.ok && body && body['ok'] === true ? correctionParts(body['parts']) : null;
    if (reply.ok && parts) {
      next.parts = parts;
    } else if (reply.ok && body && body['ok'] === false) {
      next.why =
        body['reason'] === 'too-long' && typeof body['why'] === 'string'
          ? body['why']
          : body['reason'] === 'nothing'
            ? CORRECTION_NOTHING
            : CORRECTION_FAILED;
    } else {
      throw new Error('correction not composed');
    }
  } catch {
    next.why = CORRECTION_FAILED;
  } finally {
    request.done();
  }
  next.pending = false;
  if (quiet) {
    /* Replaced, closed or edited while the request was out: that answer is not this box's, and an edit keeps
       the reader's text with Recompose beside it. */
    if (drift.corrections.get(key) !== quiet) return;
    quiet.recomposing = false;
    if (quiet.edited || drift.editor.composition?.held === quiet) quiet.stale = true;
    else if (!quiet.open || next.why === CORRECTION_NOTHING) drift.corrections.delete(key);
    else drift.corrections.set(key, next);
    drift.notify();
    return;
  }
  /* Replaced or closed while the request was out: that answer is not this box's. */
  if (drift.corrections.get(key) !== next) return;
  drift.notify();
  requestFocus(ctx, next.why ? `steer-back:${key}` : `correction:${key}`);
}

/* The press opens the box and asks the server, naming the session and nothing else, so no text the page holds
   can reach the composition. A second press closes an open box; over a refusal it asks again, as the refusal
   says. A text the reader edited or copied is kept across a close. */
export function steerBack(ctx: DriftCtx, identity: SessionIdentity): Promise<void> | undefined {
  const { drift, intent } = ctx;
  const session = liveRow(intent, identity);
  if (!session) return undefined;
  const key = compatSessKey(identity);
  const held = drift.corrections.get(key);
  if (held?.pending) return undefined;
  if (held?.open && !held.why) {
    held.open = false;
    drift.notify();
    requestFocus(ctx, `steer-back:${key}`);
    return undefined;
  }
  if (held && !held.why && typeof held.text === 'string' && Array.isArray(held.parts)) {
    held.open = true;
    drift.notify();
    requestFocus(ctx, `correction:${key}`);
    return undefined;
  }
  return composeCorrection(ctx, identity, correctionStamp(annotationOf(session)));
}

/* "Recompose": the reader asked for the record as it stands, over their edit. */
export async function recomposeCorrection(ctx: DriftCtx, identity: SessionIdentity): Promise<void> {
  /* One composition at a time: a second press while one is out asks for nothing. */
  if (ctx.drift.corrections.get(compatSessKey(identity))?.pending) return;
  const session = liveRow(ctx.intent, identity);
  return composeCorrection(ctx, identity, correctionStamp(session ? annotationOf(session) : null));
}

/* Copy writes the box's exact text and only then records it, so a paste of it coming back reads as Compass's
   words. The text is frozen at the press, so what is recorded is what was shown. Never a text composed from a
   record that no longer holds unless the reader made it theirs, and never provisional composition text. */
export async function copyCorrection(ctx: DriftCtx, identity: SessionIdentity): Promise<void> {
  const { drift, intent, shell } = ctx;
  const session = liveRow(intent, identity);
  if (!session) return;
  const key = compatSessKey(identity);
  const held = drift.corrections.get(key);
  if (!held || !Array.isArray(held.parts) || held.copying || held.pending) return;
  if (drift.editor.composition?.held === held) {
    held.cue = 'failed';
    drift.notify();
    return;
  }
  const source = sourceFor(ctx, session);
  if (!held.edited && correctionStale(held, annotationOf(session), source, session)) {
    held.cue = 'failed';
    drift.notify();
    requestFocus(ctx, `correction-copy:${key}`);
    return;
  }
  const text = correctionDraft(held);
  held.text = text;
  held.copying = true;
  let copied = false;
  try {
    const clipboard = shell.controls.clipboard();
    if (!text || !clipboard) throw new Error('clipboard unavailable');
    await clipboard.writeText(text);
    copied = true;
  } catch {
    copied = false;
  }
  shell.announcer.say('copy', copied ? 'Copied' : 'Copy unavailable');
  held.copying = false;
  held.cue = copied ? 'copied' : 'failed';
  drift.notify();
  requestFocus(ctx, `correction-copy:${key}`);
  if (!copied) return;
  const request = bounded(ctx);
  try {
    await shell.runtime.client.postCorrectionCopied({ ...identity, text }, request.signal);
  } catch {
    /* Unrecorded, a paste reads as the reader's own words: the safe side. */
  } finally {
    request.done();
  }
}

/* What the box last drew, kept on the held correction for a recomposition to freeze: written after a commit,
   never from a render. */
export function rememberShown(held: HeldCorrection, text: string): void {
  held.shownText = text;
}

/* "Updates are paused while you edit this correction": said while a board that arrived waits behind a focused,
   edited box, and taken back the moment the reader leaves it. A composition or a pointer on its way to a
   control also waits, but neither is the reader editing in place, so neither says it. */
export function syncPaused(ctx: DriftCtx, key: string, paused: boolean): void {
  const held = ctx.drift.corrections.get(key);
  if (!held) return;
  const want = paused ? CORRECTION_PAINT_PAUSED : '';
  if ((held.paintWhy ?? '') === want) return;
  held.paintWhy = want;
  ctx.drift.notify();
}
