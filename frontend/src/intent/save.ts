import { nextNumber } from '../api/bootstrap';
import type { AnnotateReceipt, SessionIdentity } from '../api/types';
import type { Row } from '../observed';
import { annotateOn, annotationLines } from './annotation';
import {
  answered,
  identityOf,
  pendingEnd,
  pendingStart,
  readInput,
  refresh,
  type Ctx,
} from './context';
import { markAndSay, say } from './cues';
import {
  adoption,
  chosenCandidate,
  directionLinesQuestion,
  discardKey,
  goalKey,
  intentChanges,
  intentDraft,
  intentKey,
  linesDraft,
  linesKey,
  linesOrigins,
  linesToSend,
  PROMPT_CHOSEN,
  type Changes,
  type Draft,
  type DraftInput,
} from './derive';
import { promptCandidate } from '../sessions/intent';
import { intentLogFor } from './logContext';
import { ADOPT_CHANGED, ADOPT_REFUSED, DISCARD_DWELL_MS, HELD_OUTCOME_CUES } from './sentences';

/* Save intent, the prompt adoption it chains, and Discard everything: every write of the reader's own
   words. Each is one explicit press. Nothing here is retried, and nothing starts from a mount, a poll or a
   reconnect; a request is sent once, and an answer the page could not read is said as unknown, never as a
   refusal. */

const compat = (row: Row): string =>
  `${String(row['harness'] || '')}:${String(row['sid'] || row['session'] || '')}`;

/* What a typed save's reply says, from the store's own `outcome` token and not from `persisted`, which is
   one bit for four sentences. An unknown token, from a server newer than this page, falls back on
   `persisted`, which keeps its meaning across builds. */
export function outcomeKind(saved: AnnotateReceipt): string {
  return (
    HELD_OUTCOME_CUES[String(saved.outcome || '')] ??
    (saved.persisted === true ? 'saved' : 'unpersisted')
  );
}

/* The lines a press means to save, read before its first await: the words and each line's stored position.
   The chain posts these and never reads the drafts again, so anything typed while the adoption was open
   stays held. */
export interface FrozenLines {
  readonly sent: string[];
  readonly origins: (number | null)[];
}

export function freezeLines(input: DraftInput): FrozenLines {
  const { held, session, annotation } = input;
  const draft = linesDraft(held, session, annotation);
  const from = linesOrigins(held, linesKey(session), draft);
  return {
    sent: linesToSend(draft),
    origins: draft
      .map((text, index) => [text, from[index] ?? null] as const)
      .filter(([text]) => String(text || '').trim())
      .map(([, origin]) => origin),
  };
}

/* After a press that adopted the draft, the held goal goes only while it still equals that draft, so nothing
   typed while the request was open is dropped. */
export function forgetAdopted(ctx: Ctx, session: Row, draft: Draft | null): void {
  const key = goalKey(session);
  if (draft && ctx.held.goals.get(key) === draft.text) {
    ctx.held.cleared.delete(key);
    ctx.held.goals.delete(key);
    ctx.held.notify();
  }
}

/* After a press that adopted a chosen prompt, the held choice goes only while it is that prompt, by the
   fact, the words and the time the adoption named. Another prompt picked while the request was open is the
   reader's newer choice and stays. */
export function forgetChosen(ctx: Ctx, session: Row, adopted: Draft | null): void {
  const key = goalKey(session);
  const held = ctx.held.chosen.get(key);
  if (
    adopted &&
    adopted.source === PROMPT_CHOSEN &&
    held &&
    held.factId === adopted.factId &&
    held.text === adopted.text &&
    held.at === adopted.at
  ) {
    ctx.held.cleared.delete(key);
    ctx.held.chosen.delete(key);
    ctx.held.notify();
  }
}

function candidateFor(ctx: Ctx, input: DraftInput, source: string): Draft | null {
  if (source === PROMPT_CHOSEN) return chosenCandidate(ctx.held, input.contexts, input.session);
  if (source === 'first-prompt' || source === 'latest-prompt') {
    return promptCandidate(input.session, source);
  }
  return null;
}

/* True when adopted, "unconfirmed" when no answer could be read, false when refused. */
export type Adopted = boolean | 'unconfirmed';

/* Always under Save intent's pending entry, whose `signal` bounds it: choosing a prompt only fills the box.
   `minted`, where given, receives the revision the adoption wrote. */
export async function adoptPrompt(
  ctx: Ctx,
  identity: SessionIdentity,
  row: Row,
  source: string,
  signal: AbortSignal,
  minted: { revision: number } | null,
): Promise<Adopted> {
  const input = readInput(ctx, identity, row);
  if (!input) return false;
  const candidate = candidateFor(ctx, input, source);
  if (!candidate || candidate.at === null || !annotateOn(input.payload)) return false;
  const expected = nextNumber(row['annotation_revision']) || 0;
  const reply = answered(
    await ctx.shell.runtime.client.postAnnotate(
      { ...identity, ...adoption(candidate), expected_revision: expected },
      signal,
    ),
  );
  if (reply.kind === 'lost') {
    /* No answer is not a changed prompt: the save's own unconfirmed sentence says it, beside Save intent. */
    ctx.held.mark(intentKey(row), 'unconfirmed');
    await refresh(ctx);
    return 'unconfirmed';
  }
  const body = reply.body;
  try {
    if (reply.ok && body && ['untrusted', 'unreadable'].includes(String(body.outcome || ''))) {
      /* Not a changed prompt: the store could not take the save at all, and saying the prompt changed would
         send the reader to the wrong place. */
      ctx.held.requests.set(compat(row), {
        ...ctx.held.requests.get(compat(row)),
        message: ADOPT_REFUSED[String(body.outcome)] ?? '',
      });
      return false;
    }
    if (!reply.ok || !body || !body.persisted) throw new Error('adoption not saved');
    /* The store captures this receipt under its lock. A discarded session can mint above n+1, while the
       handler's current revision may belong to a later writer. An unchanged goal only confirms the frozen
       checklist baseline, never a newer one. */
    const own = body.saved_revision;
    const ownsBaseline =
      body.outcome === 'stored' || (body.outcome === 'unchanged' && own === expected);
    if (minted) {
      minted.revision =
        typeof own === 'number' &&
        Number.isSafeInteger(own) &&
        own > 0 &&
        ownsBaseline &&
        body.revision === own
          ? own
          : 0;
    }
    /* Only what this press adopted goes, and only while it is still what the box holds: the reply can arrive
       after the reader typed other words or picked another prompt, and the adoption's words are then the
       saved goal beneath a newer edit that is still theirs. */
    // An earlier press's "changed" or "refused" no longer stands once this one landed.
    const request = ctx.held.requests.get(compat(row));
    if (request && !request.pending) request.message = '';
    /* After the refresh, so the box keeps showing the adopted words until the row that holds them is drawn. */
    try {
      await refresh(ctx);
    } finally {
      forgetAdopted(ctx, row, candidate);
      forgetChosen(ctx, row, candidate);
    }
    return true;
  } catch {
    ctx.held.requests.set(compat(row), {
      ...ctx.held.requests.get(compat(row)),
      message: ADOPT_CHANGED,
    });
    return false;
  } finally {
    ctx.held.notify();
  }
}

/* Whether the refreshed row shows this save landed: a revision above the one it was drafted against, holding
   the goal and lines it sent. */
function landed(
  ctx: Ctx,
  identity: SessionIdentity,
  body: Record<string, unknown>,
  sent: readonly string[] | null,
): boolean {
  const annotation = readInput(ctx, identity)?.annotation;
  const expected = typeof body['expected_revision'] === 'number' ? body['expected_revision'] : 0;
  if (!annotation || !((nextNumber(annotation['revision']) || 0) > expected)) return false;
  if (typeof body['goal'] === 'string' && String(annotation['goal'] || '') !== body['goal']) {
    return false;
  }
  return (
    !sent ||
    JSON.stringify(annotationLines(annotation).map((line) => line.text)) === JSON.stringify(sent)
  );
}

/* The drafts a landed save carried, dropped only while each box still holds what was sent, so nothing typed
   during the request is lost. */
function forgetSent(
  ctx: Ctx,
  row: Row,
  changes: Changes,
  body: Record<string, unknown>,
  sent: readonly string[] | null,
): void {
  const goal = goalKey(row);
  const lines = linesKey(row);
  if (changes.goal && ctx.held.goals.get(goal) === body['goal']) ctx.held.goals.delete(goal);
  // Typed words replaced the choice in the store, so it no longer stands in the box.
  if (changes.goal) {
    ctx.held.cleared.delete(goal);
    ctx.held.chosen.delete(goal);
  }
  const held = ctx.held.lines.get(lines);
  if (sent && held && JSON.stringify(linesToSend(held)) === JSON.stringify(sent)) {
    ctx.held.lines.delete(lines);
    ctx.held.origins.delete(lines);
  }
  ctx.held.notify();
}

interface Chain {
  readonly frozen: FrozenLines;
  readonly revision: number;
}

const ONLY_LINES: Changes = {
  goal: false,
  lines: true,
  typed: '',
  chosen: false,
  pending: false,
  adoptable: false,
  any: true,
  undoable: true,
};

/* The save itself, under the press's one pending entry: a choice chains its adoption and then the lines, and
   neither takes a guard of its own. Returns the cue kind it stamped, for the caller to say after the paint,
   or null. `chain` is the second stage only: the lines the press froze and the revision the adoption minted.
   It reads neither the drafts nor the row again. */
async function saveWork(
  ctx: Ctx,
  identity: SessionIdentity,
  row: Row,
  signal: AbortSignal,
  chain: Chain | null,
): Promise<string | null> {
  const input = readInput(ctx, identity, row);
  if (!input) return null;
  const key = intentKey(row);
  const changes = chain ? ONLY_LINES : intentChanges(input);
  const frozen = chain ? chain.frozen : changes.lines ? freezeLines(input) : null;
  if (changes.chosen || changes.pending || (changes.lines && changes.adoptable)) {
    /* Adopt the chosen or untouched drafted goal first, then save the frozen lines against its locked
       receipt. `/api/annotate` takes an adoption or typed words in one request, so changed lines must not
       leave the displayed draft unsaved. */
    const source =
      changes.chosen || changes.pending ? PROMPT_CHOSEN : (intentDraft(input)?.source ?? '');
    const minted = { revision: 0 };
    const adopted = await adoptPrompt(ctx, identity, row, source, signal, minted);
    if (adopted === true && frozen) {
      /* Only the lines the press held, with no goal, and against the revision the adoption minted rather
         than the refreshed row's, so a newer revision another tab saved in between is refused instead of
         overwritten. A choice or words made while the adoption was open are theirs, and this request does
         not read them. */
      if (!(minted.revision > 0)) {
        ctx.held.mark(key, 'error');
        return 'error';
      }
      return saveWork(ctx, identity, row, signal, { frozen, revision: minted.revision });
    }
    if (adopted === true) ctx.held.mark(key, 'saved');
    return adopted === true ? 'saved' : adopted === 'unconfirmed' ? 'unconfirmed' : null;
  }
  if (!changes.any) {
    /* The goal back at the draft adopts it, never a typed save of an excerpt. */
    const drafted = intentDraft(input);
    if (drafted && changes.typed === drafted.text) {
      const adopted = await adoptPrompt(ctx, identity, row, drafted.source, signal, null);
      // Marked as the chained adoption marks it, so an earlier "Not confirmed" does not outlive this save.
      if (adopted === true) ctx.held.mark(key, 'saved');
      return adopted === true ? 'saved' : adopted === 'unconfirmed' ? 'unconfirmed' : null;
    }
    return null;
  }
  const body: Record<string, unknown> = { harness: identity.harness, sid: identity.sid };
  if (changes.goal) body['goal'] = changes.typed;
  else if (changes.lines) body['goal'] = null;
  const sent = frozen ? frozen.sent : null;
  if (frozen) {
    body['lines'] = frozen.sent;
    body['origins'] = frozen.origins;
  }
  body['expected_revision'] = chain
    ? chain.revision
    : nextNumber(input.annotation?.['revision']) || 0;
  const reply = answered(
    await ctx.shell.runtime.client.postAnnotate(
      body as { harness: string; sid: string; expected_revision: number },
      signal,
    ),
  );
  if (reply.kind === 'lost') {
    /* No answer, an abort at the bound, or a reply that could not be read: the save may or may not have
       landed, so the page says it cannot tell, and the drafts stay. Then it looks: a refresh whose row
       carries a newer revision holding exactly what was sent was this save. */
    ctx.held.mark(key, 'unconfirmed');
    await refresh(ctx);
    if (landed(ctx, identity, body, sent)) {
      forgetSent(ctx, row, changes, body, sent);
      ctx.held.mark(key, 'saved');
      return 'saved';
    }
    return 'unconfirmed';
  }
  const saved = reply.body;
  // `ok`, which is what `/api/annotate` answers with. `persisted` beside it is whether the write reached
  // disk, and a false there is not a failed save: the words are held for this run and the store says so.
  if (!reply.ok || !saved || saved.ok !== true) {
    // The drafts stay. Losing what someone typed to report a failure is the one outcome worse than it.
    ctx.held.mark(key, 'error');
    return 'error';
  }
  const kind = outcomeKind(saved);
  /* A draft goes only where the words are on disk, which is a minted revision or a repeat of the one already
     there, and only while its box still holds what was sent. `persisted:false` leaves the revision in this
     process alone, and the next collection reloads the file and drops it: dropping the draft then destroyed
     the only remaining copy of what someone typed. */
  ctx.held.mark(key, kind);
  if (kind !== 'saved' && kind !== 'unchanged') {
    // Nothing landed, so the store's answer is the whole outcome and no refresh has words to draw.
    void refresh(ctx);
    return kind;
  }
  /* Forgotten after the refresh, not before: with the draft gone and the row not yet redrawn, the boxes showed
     the drafted prompt and emptied outcome lines for as long as the board took to answer. */
  try {
    await refresh(ctx);
  } finally {
    forgetSent(ctx, row, changes, body, sent);
  }
  return kind;
}

/* Save intent: both fields in one write. The typed arm of `/api/annotate` takes `goal` and `lines` together,
   an absent or null field being "leave this one alone", so the press sends only what changed and a stale
   draft of one field cannot overwrite a save of the other. One request rather than two chained ones, so
   there is one revision and one outcome to report. It names the revision both boxes were drawn against, so a
   save from a tab another tab has moved on is refused and the typed words stay in the boxes. */
export async function saveIntent(ctx: Ctx, row: Row): Promise<void> {
  const identity = identityOf(row);
  if (!identity) return;
  const input = readInput(ctx, identity, row);
  if (!input) return;
  const key = intentKey(row);
  const control = `${key}:save`;
  /* The same reckoning the footer decides `live` with, so the control and the gate cannot disagree. Without
     it an inert-but-reachable control mints a revision identical to the stored one. An inert press starts
     nothing. */
  const changes = intentChanges(input);
  if (directionLinesQuestion(ctx.held, row)) return;
  if (!changes.any && !changes.chosen && !changes.adoptable) return;
  const press = pendingStart(ctx, control, 'Saving…', 'Saving your intent.');
  if (!press) return;
  ctx.held.notify();
  let said: string | null = null;
  try {
    said = await saveWork(ctx, identity, row, press.signal, null);
  } finally {
    pendingEnd(ctx, control, press);
    ctx.held.requestFocus(control);
    /* The outcome is said once it is drawn, never before the paint that shows it. */
    if (said) say(ctx, key, said);
  }
}

/* The act the endpoint has always had and no control reached. Section scope, not field scope:
   `annotations.clear` drops the whole entry, so a control inside a field would offer an act it cannot
   perform. Labelled `discard everything` and never `clear`, because the shorter word is already printed
   beside each box for a weaker act on a different store. Armed by the first press and performed by the
   second, through the cue lane and its 30 second TTL rather than a dialog; an arm that lapses on its own
   leaves a reader who walked away with a disarmed control. */
export function pressDiscard(ctx: Ctx, row: Row, detail: number): void {
  const identity = identityOf(row);
  if (!identity) return;
  const key = discardKey(row);
  // Read before the kind, which a lapse would drop.
  const armedAt = ctx.held.kind(key) === 'discard-armed' ? ctx.held.stampOf(key) : 0;
  const slip = detail > 1 || ctx.shell.clock.now() - armedAt < DISCARD_DWELL_MS;
  if (ctx.held.kind(key) !== 'discard-armed' || slip) {
    /* Arm, or re-arm. Nothing is posted until the reader has read what the second press will do and pressed
       again, and a press too soon after the arm to have read it is the double-click that used to confirm in
       one gesture, so it buys another dwell rather than the write. */
    markAndSay(ctx, key, 'discard-armed');
    ctx.held.requestFocus(key);
    return;
  }
  void discardAnnotation(ctx, row, identity);
}

async function discardAnnotation(ctx: Ctx, row: Row, identity: SessionIdentity): Promise<void> {
  const key = discardKey(row);
  const press = pendingStart(ctx, key, 'Discarding…', 'Discarding.');
  if (!press) return;
  ctx.held.notify();
  try {
    const reply = answered(
      await ctx.shell.runtime.client.postAnnotate({ ...identity, clear: true }, press.signal),
    );
    if (reply.kind === 'lost') {
      /* No answer: disarmed, said as unknown, and never re-armed on its own, so a second press is the
         reader's after the refresh shows what stands. */
      markAndSay(ctx, key, 'discard-unconfirmed');
      await refresh(ctx);
      return;
    }
    if (!reply.ok) throw new Error(`HTTP ${String(reply.status)}`);
    const body = reply.body;
    if (!body || body.ok !== true) throw new Error('discard not confirmed');
    const outcome = String(body.outcome || '');
    /* The store's own token, with `persisted` as the fallback an older or newer server leaves: one bit
       cannot carry three sentences. */
    const result =
      outcome === 'unreadable'
        ? 'discard-held'
        : ['stored', 'refused', 'unwritable', 'untrusted'].includes(outcome)
          ? `discard-${outcome}`
          : body.persisted === true
            ? 'discard-stored'
            : 'discard-unwritable';
    /* A discard is one act over two stores and the second half fails on its own. `withdrew` is the departure
       store's answer, so the categorical sentence is not printed over rows this page is about to redraw
       with the discarded words still in them. `=== false` and not falsiness: a server that predates the
       field omits it, and an absent answer must leave the sentence it had. */
    const kind =
      result === 'discard-stored' && body.withdrew === false ? 'discard-unwithdrawn' : result;
    if (kind === 'discard-stored' || kind === 'discard-unwithdrawn') {
      // The independent log may already hold these words, even if the next dashboard fetch fails.
      intentLogFor(ctx.shell).invalidate();
      /* The drafts go with the annotation. They are an independent lane, so a half-typed box would otherwise
         sit over an empty store and the next save would mint revision 1 of what the reader just
         discarded. */
      ctx.held.cleared.delete(goalKey(row));
      ctx.held.goals.delete(goalKey(row));
      ctx.held.lines.delete(linesKey(row));
      ctx.held.origins.delete(linesKey(row));
    }
    markAndSay(ctx, key, kind);
    ctx.held.notify();
    await refresh(ctx);
  } catch {
    // Nothing was deleted that this page can see, which is what the refusal sentence says. No retry.
    markAndSay(ctx, key, 'discard-refused');
  } finally {
    pendingEnd(ctx, key, press);
    ctx.held.requestFocus(key);
  }
}

/* Escape on the ARMED discard control, and only then: the arm is dropped deliberately, so the next one is not a
   repeat of this one. Unarmed, Escape keeps meaning "leave this view". */
export function disarmDiscard(ctx: Ctx, row: Row): boolean {
  const key = discardKey(row);
  if (ctx.held.kind(key) !== 'discard-armed') return false;
  ctx.held.drop(key);
  ctx.held.requestFocus(key);
  return true;
}
