import { nextNumber, payloadSessions } from '../api/bootstrap';
import { compatSessKey, contextKey, stableProjectKey } from '../api/identity';
import type { SessionIdentity } from '../api/types';
import type { Row } from '../observed';
import { annotationOf, heldCap, scrub, stripPasteWrapper, trimToRule } from './annotation';
import { markAndSay } from './cues';
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
  type Ctx,
} from './context';
import {
  adoption,
  directionLinesQuestion,
  directionsOpen,
  directionWhy,
  editedRefusal,
  goalKey,
  intentChanges,
  intentDraft,
  intentKey,
  intentUnsaved,
  linesChanged,
  linesKey,
  linesOrigins,
  savedLines,
  type DraftInput,
} from './derive';
import type { DirectionLine } from './held';
import { forgetAdopted, outcomeKind, saveIntent } from './save';
import {
  DIRECTION_UNOPENED,
  directionFailure,
  HELD_CUES,
  INTENT_CHOSEN_SAID,
  INTENT_EDITED,
  keptDirections,
  KEEP_READ_FIRST,
  KEEP_REFUSED,
  KEEP_UNCONFIRMED,
  KEEP_UNOPENED,
  KEEP_BATCH_LIMIT,
} from './sentences';
import { laterDirections, workSource, type WorkEntry } from './work';

/* Later directions: "Add it to my intent" opens one as a pending line the reader reviews and saves, "Use this
   as my goal" fills the goal box with it, and Keep settles every direction the reader was shown. Each is one
   explicit press, sent once and never retried. A direction is read whole before anything is settled over it,
   because Keep settles every direction it was shown and the question quotes only the earliest one's first
   sentence. */

const compat = compatSessKey;

function feedback(ctx: Ctx, control: string, message: string): void {
  ctx.held.actionFeedback.set(control, message);
  announce(ctx, `action:${control}`, message);
  ctx.held.notify();
}

function startFeedback(ctx: Ctx, control: string): void {
  ctx.held.actionFeedback.delete(control);
  ctx.shell.announcer.forget(`action:${control}`);
}

/* The session's focused observed record, read from the contexts the board holds. */
function sourceOf(ctx: Ctx, input: DraftInput, projectKey: string) {
  return workSource(
    input.contexts,
    projectKey,
    input.session,
    ctx.shell.runtime.store
      .getSnapshot()
      .records.get(contextKey(projectKey, input.session as never)),
  );
}

/* The pending line, from its fact id on every render and gone once its direction is no longer open: a number
   kept from the press can name a row the list no longer draws. Run after a render by the panel. */
export function reconcileDirection(ctx: Ctx, input: DraftInput, projectKey: string): void {
  const key = compat(input.session);
  const held = ctx.held.directions.get(key);
  if (!held || typeof held.text !== 'string') return;
  const source = sourceOf(ctx, input, projectKey);
  const record = ctx.shell.runtime.store
    .getSnapshot()
    .records.get(contextKey(projectKey, input.session as never));
  // Unread older pages cannot disprove an opened direction. Its draft belongs to Intent, not the page cache.
  if (
    held.recordOrigin &&
    !record?.reachedStart &&
    !(source.all ?? source.entries).some((entry) => entry.id === held.factId)
  )
    return;
  const read = source.state === 'read' || source.state === 'empty';
  /* Opened by Update intent instead, a direction an analysis's Keep already settled is still one to add, so
     that line stands while its direction is any later direction; the question's own Add keeps the
     narrower open set. */
  const open = held.later
    ? laterOf(input, source.all || source.entries)
    : directionsOpen(input, source);
  if (read && !open.some((entry) => String(entry.id || '') === held.factId)) {
    ctx.held.directions.delete(key);
    ctx.held.notify();
  }
}

function laterOf(input: DraftInput, entries: readonly WorkEntry[]): WorkEntry[] {
  return laterDirections(input.annotation, entries, input.session, intentDraft(input));
}
export { laterOf };

/* The text the store would hold for a pasted direction: a multi-line direction is the one line the store
   would hold. The scrub is not a summary. */
export async function openDirection(
  ctx: Ctx,
  row: Row,
  factId: string,
  n: string | null,
  later = false,
  action = 'direction-add',
  focusControl?: string,
): Promise<void> {
  const identity = identityOf(row);
  if (!identity) return;
  const key = compat(row);
  /* A second press while a line is pending goes to that line: reopening it would put the server's text back
     over the reader's edits. */
  const open = ctx.held.directions.get(key);
  if (open && (open.opening || typeof open.text === 'string')) {
    if (!open.opening) ctx.held.requestFocus(`direction:${key}`);
    return;
  }
  const control = focusControl ?? `${action}:${key}`;
  startFeedback(ctx, control);
  const press = pendingStart(ctx, control, 'Opening…');
  if (!press) return;
  const snapshot = ctx.shell.runtime.store.getSnapshot();
  const label = String(row['project'] ?? '');
  const projectKey = stableProjectKey({
    label,
    sessions: snapshot.data
      ? payloadSessions(snapshot.data).rows.filter((session) => session.project === label)
      : [],
  });
  const recordOrigin = snapshot.records
    .get(contextKey(projectKey, identity))
    ?.entries.some((entry) => entry.fact_id === factId);
  const origin = recordOrigin ? { recordOrigin: true } : {};
  ctx.held.directions.set(key, { factId, n, later, opening: true, ...origin });
  ctx.held.notify();
  let held: DirectionLine;
  try {
    const reply = answered(
      await ctx.shell.runtime.client.postDirection({ ...identity, fact_id: factId }, press.signal),
    );
    const body = reply.kind === 'answered' && reply.ok ? reply.body : null;
    if (body && body.ok === true && typeof body.text === 'string') {
      held = {
        factId,
        n,
        later,
        text: trimToRule(scrub(stripPasteWrapper(body.text))),
        clipped: body.clipped === true,
        replace: null,
      };
    } else if (body && body.ok === false) {
      held = { factId, n, later, error: directionFailure('add', body.reason) };
    } else {
      throw new Error('direction not opened');
    }
  } catch {
    held = { factId, n, later, error: DIRECTION_UNOPENED };
  } finally {
    pendingEnd(ctx, control, press);
  }
  ctx.held.directions.set(key, { ...held, ...origin });
  if (held.error) feedback(ctx, control, held.error);
  ctx.held.requestFocus(held.error ? control : `direction:${key}`);
}

/* A keystroke in the pending line: the whole text stays, and a line over the bound is refused at the save
   rather than cut here. */
export function typeDirection(ctx: Ctx, row: Row, raw: string): string {
  const held = ctx.held.directions.get(compat(row));
  const value = scrub(raw);
  if (!held || typeof held.text !== 'string') return value;
  ctx.held.clearActionFeedback(compat(row));
  held.text = value;
  held.cue = '';
  ctx.held.notify();
  return value;
}

export function cancelDirection(ctx: Ctx, row: Row): void {
  const key = compat(row);
  ctx.held.clearActionFeedback(key);
  ctx.held.directions.delete(key);
  ctx.held.requestFocus(`direction-add:${key}`);
}

export function replaceDirection(ctx: Ctx, row: Row, index: number): void {
  const key = compat(row);
  const held = ctx.held.directions.get(key);
  if (held && Number.isInteger(index) && index >= 0 && index < 6) {
    held.replace = held.replace === index ? null : index;
    ctx.held.requestFocus(`direction-replace:${key}:${String(index)}`);
  }
}

function currentRow(ctx: Ctx, row: Row): Row {
  const identity = identityOf(row);
  return (identity ? liveRow(ctx, identity) : null) ?? row;
}

/* The stored line, and its place in the store's new list as its origin, join a lines draft the reader typed
   into while Add's save was open. The origin counts only once the refresh has published the revision the save
   minted; before that the line is offered as added here, and the store gives it a source of its own. A
   replace takes the place of the line it replaced where the draft still holds that line untouched. The
   stored list is read from the row the refresh published: the poll hands the page a new object, so the one
   this save captured never moves. */
function takeAdded(
  ctx: Ctx,
  row: Row,
  key: string,
  draft: string[],
  held: DirectionLine,
  before: Row | null,
): void {
  const annotation = annotationOf(currentRow(ctx, row));
  const saved = savedLines(annotation);
  const moved =
    (nextNumber(annotation?.['revision']) || 0) > (nextNumber(before?.['revision']) || 0);
  const index = held.replace != null ? held.replace : saved.length - 1;
  const text = moved && saved[index] != null ? saved[index] : (held.text ?? '');
  const origin = moved && saved[index] != null ? index : null;
  const lines = draft.slice();
  const origins = linesOrigins(ctx.held, key, draft);
  const replaced = held.replace != null ? savedLines(before)[held.replace] : null;
  const at = replaced != null ? origins.indexOf(held.replace ?? -1) : -1;
  if (at >= 0 && moved && lines[at] === replaced) {
    lines[at] = text ?? '';
    origins[at] = origin;
  } else {
    lines.push(text ?? '');
    origins.push(origin);
  }
  ctx.held.lines.set(key, lines);
  ctx.held.origins.set(key, origins);
}

const rowRevision = (ctx: Ctx, row: Row): number =>
  nextNumber(annotationOf(currentRow(ctx, row))?.['revision']) || 0;

export async function saveDirection(ctx: Ctx, row: Row): Promise<void> {
  const identity = identityOf(row);
  if (!identity) return;
  const key = compat(row);
  const held = ctx.held.directions.get(key);
  if (!held || typeof held.text !== 'string' || held.pending) return;
  const input = readInput(ctx, identity, row);
  if (!input) return;
  const annotation = input.annotation;
  const cap = heldCap(input.payload);
  const why = directionWhy(held, input, cap);
  if (why || !held.text.trim()) {
    if (why) {
      announce(ctx, `direction:${key}`, why);
      ctx.held.requestFocus(`${intentKey(row)}:save`);
    }
    return;
  }
  // Over a draft the one write adopts it, as the owner ruled.
  const draft = intentDraft(input);
  const linesFor = linesKey(row);
  const control = `${intentKey(row)}:save`;
  const press = pendingStart(ctx, control, 'Saving…', 'Saving the line.');
  if (!press) return;
  held.pending = true;
  held.cue = '';
  ctx.held.notify();
  try {
    const sent = await ctx.shell.runtime.client.postAnnotate(
      {
        ...identity,
        add_direction: held.factId,
        text: held.text,
        expected_revision: nextNumber(annotation?.['revision']) || 0,
        ...(held.replace != null ? { replace: held.replace } : {}),
        ...adoption(draft),
      },
      press.signal,
    );
    const reply = answered(sent);
    if (reply.kind === 'lost') {
      // No answer is not a refusal: the page cannot tell whether it landed.
      held.cue = 'unconfirmed';
      await refresh(ctx);
      return;
    }
    if (!reply.ok) throw new Error(`HTTP ${String(reply.status)}`);
    const saved = reply.body;
    if (!saved || saved.ok !== true) throw new Error('save not confirmed');
    const kind = outcomeKind(saved);
    let typed = false;
    if (kind === 'saved' || kind === 'unchanged') {
      ctx.held.directions.delete(key);
      forgetAdopted(ctx, row, draft);
      /* A lines draft still equal to the list this save stood on would hide the added line and delete it at
         the next line save, so it goes. One the reader changed while the save was open is theirs: it stays,
         and takes the stored line below. */
      const lines = ctx.held.lines.get(linesFor);
      if (lines && !linesChanged(lines, annotation)) {
        ctx.held.lines.delete(linesFor);
        ctx.held.origins.delete(linesFor);
      } else if (lines && kind === 'saved') typed = true;
      markAndSay(ctx, linesFor, kind);
    } else {
      held.cue = kind;
    }
    await refresh(ctx);
    /* A poll that starts while that refresh is open supersedes it, and the superseded one returns without
       publishing, so the merge read the pre-save row. Refresh again, a bounded number of times, until the
       row carries the revision the save minted. */
    const minted = nextNumber(saved.revision) || 0;
    for (let tries = 0; typed && tries < 3 && rowRevision(ctx, row) < minted; tries += 1) {
      await refresh(ctx);
    }
    const typing = typed ? ctx.held.lines.get(linesFor) : null;
    if (typing) takeAdded(ctx, row, linesFor, typing, held, annotation ? row : null);
  } catch {
    held.cue = 'error';
  } finally {
    held.pending = false;
    pendingEnd(ctx, control, press);
    ctx.held.requestFocus(control);
  }
}

/* "Use this as my goal": fills the goal box with the direction as a pending adoption, over words that are not
   on screen only after the reader has saved or undone their edit. Never from a poll, a mount or a retry. */
export async function adoptDirectionAsGoal(
  ctx: Ctx,
  row: Row,
  factId: string,
  focusControl?: string,
): Promise<void> {
  const identity = identityOf(row);
  if (!identity) return;
  const first = readInput(ctx, identity, row);
  if (!first) return;
  const revision = nextNumber(row['annotation_revision']) || 0;
  if (intentUnsaved(first)) {
    announce(ctx, intentKey(row), INTENT_EDITED);
    return;
  }
  const control = `direction-goal:${compat(row)}`;
  const focus = focusControl ?? control;
  startFeedback(ctx, focus);
  const press = pendingStart(ctx, control, 'Opening…');
  if (!press) return;
  const key = goalKey(row);
  let filled = false;
  const refuse = (reason?: string) => feedback(ctx, focus, directionFailure('goal', reason));
  try {
    const reply = answered(
      await ctx.shell.runtime.client.postDirection({ ...identity, fact_id: factId }, press.signal),
    );
    const answer = reply.kind === 'answered' && reply.ok ? reply.body : null;
    const current = liveRow(ctx, identity) ?? row;
    const now = readInput(ctx, identity, current);
    if (
      !now ||
      intentUnsaved(now) ||
      (nextNumber(current['annotation_revision']) || 0) !== revision
    ) {
      announce(ctx, intentKey(row), INTENT_EDITED);
      return;
    }
    const choice = answer && (answer as Record<string, unknown>)['goal_choice'];
    const record =
      choice && typeof choice === 'object' ? (choice as Record<string, unknown>) : null;
    if (
      answer?.ok !== true ||
      !record ||
      record['fact_id'] !== factId ||
      typeof record['text'] !== 'string' ||
      !record['text'].trim() ||
      !((nextNumber(record['at']) || 0) > 0)
    ) {
      refuse(answer?.reason);
      return;
    }
    filled = true;
    ctx.held.chosen.set(key, {
      factId,
      text: stripPasteWrapper(record['text']),
      at: nextNumber(record['at']),
      cut: record['cut'] === true,
      direction: true,
      linesAnswer: savedLines(first.annotation).length ? null : 'keep',
    });
    ctx.held.cleared.delete(key);
    ctx.held.goals.delete(key);
    /* The box starts at the rule, not the whole message. The choice keeps the whole words so Undo returns to
       them, and the trimmed start is a typed edit over them, which Save intent saves as typed words. */
    const rule = trimToRule(stripPasteWrapper(record['text']));
    if (rule && rule !== stripPasteWrapper(record['text'])) ctx.held.goals.set(key, rule);
    ctx.held.drop(intentKey(row));
    ctx.held.directions.delete(compat(row));
    announce(ctx, `${key}:chosen`, INTENT_CHOSEN_SAID);
  } catch {
    refuse();
  } finally {
    pendingEnd(ctx, control, press);
    ctx.held.requestFocus(filled ? key : focus);
  }
}

/* The standing outcome lines, kept or cleared with the goal a direction became. Clearing is an edit of the
   draft, never a save. */
export function answerLines(ctx: Ctx, row: Row, answer: 'keep' | 'clear'): void {
  const choice = ctx.held.chosen.get(goalKey(row));
  if (!choice) return;
  ctx.held.clearActionFeedback(compat(row));
  choice.linesAnswer = answer;
  if (answer === 'clear') {
    ctx.held.lines.set(linesKey(row), []);
    ctx.held.origins.set(linesKey(row), []);
  }
  ctx.held.notify();
}

/* ---- Keep ---- */

export type WholeResult = {
  readonly kind: 'read' | 'shown' | 'refused';
  readonly message?: string;
};

// Reads the words of the open directions the page has not yet held, so they are drawn before a press may
// settle them (DEC-27). The question loads them on mount; this press reads again only when that failed.
async function readWhole(
  ctx: Ctx,
  identity: SessionIdentity,
  row: Row,
  pending: readonly WorkEntry[],
  revision: number,
  signal: AbortSignal,
): Promise<WholeResult> {
  const key = compat(row);
  const held = ctx.held.wholes.get(key) ?? {
    texts: new Map(),
    drawn: new Set<string>(),
    revision: null,
  };
  ctx.held.wholes.set(key, held);
  let refusal = KEEP_UNOPENED;
  let refused = false;
  const alreadyShown = new Set(
    pending
      .map((entry) => String(entry.id || ''))
      .filter((id) => held.drawn.has(id) && !held.texts.get(id)?.clipped),
  );
  const missing = pending.filter(
    (entry) =>
      !held.texts.has(String(entry.id || '')) || held.texts.get(String(entry.id || ''))?.clipped,
  );
  // One scan checks all identities, including conflicting copies after a match.
  if (missing.length > 64) return { kind: 'refused', message: KEEP_BATCH_LIMIT };
  if (missing.length) {
    try {
      const reply = answered(
        await ctx.shell.runtime.client.postDirections(
          { ...identity, fact_ids: missing.map((entry) => String(entry.id || '')) },
          signal,
        ),
      );
      const results = reply.kind === 'answered' && reply.ok ? reply.body?.results : null;
      if (!Array.isArray(results) || results.length !== missing.length) {
        refused = true;
      } else {
        for (const [index, entry] of missing.entries()) {
          const body = results[index];
          const id = String(entry.id || '');
          if (body?.ok === true && typeof body.text === 'string') {
            held.texts.set(id, {
              text: stripPasteWrapper(body.text),
              clipped: body.clipped === true,
            });
            if (body.clipped === true) refused = true;
          } else {
            if (!refused && body?.ok === false) refusal = directionFailure('keep', body.reason);
            refused = true;
          }
        }
      }
    } catch {
      refused = true;
    }
  }
  if (signal.aborted || pending.some((entry) => held.texts.get(String(entry.id || ''))?.clipped))
    refused = true;
  if (refused) {
    held.drawn = new Set(
      pending.map((entry) => String(entry.id || '')).filter((id) => held.texts.has(id)),
    );
    held.revision = revision;
    return { kind: 'refused', message: refusal };
  }
  const ids = pending.map((entry) => String(entry.id || ''));
  if (ids.every((id) => alreadyShown.has(id))) return { kind: 'read' };
  held.drawn = new Set(ids);
  held.revision = revision;
  return { kind: 'shown' };
}

/* The words of every open direction, read once they are drawn and not on a press, so the question quotes
   what each choice acts on and the first press of Leave it settles words already on screen. It adds no session or
   store state of its own. A failed read leaves the quote at the entry's first sentence
   and Leave it's own press reads again, as it did. One read per set of directions at a time. */
const loading = new Set<string>();

export async function loadWholes(ctx: Ctx, row: Row, projectKey: string): Promise<void> {
  const identity = identityOf(row);
  if (!identity) return;
  const input = readInput(ctx, identity, row);
  if (!input) return;
  const pending = directionsOpen(input, sourceOf(ctx, input, projectKey));
  if (!pending.length) return;
  const key = compat(row);
  const ids = pending.map((entry) => String(entry.id || ''));
  const held = ctx.held.wholes.get(key);
  if (ids.every((id) => held?.texts.has(id) && !held.texts.get(id)?.clipped)) {
    if (held && !ids.every((id) => held.drawn.has(id))) {
      held.drawn = new Set(ids);
      ctx.held.notify();
    }
    return;
  }
  const guard = `${key}:${ids.join(',')}`;
  if (loading.has(guard)) return;
  loading.add(guard);
  try {
    await readWhole(
      ctx,
      identity,
      row,
      pending,
      nextNumber(input.annotation?.['revision']) || 0,
      new AbortController().signal,
    );
  } finally {
    loading.delete(guard);
    ctx.held.notify();
  }
}

/* Save intent, over a pending direction line: the one save for the card. Words typed in the boxes, or a
   prompt adopted, are saved first, because the line is added against the revision they mint; the line then
   goes in its own write, and only if the first left nothing unsaved. */
export async function saveIntentAndLine(ctx: Ctx, row: Row): Promise<void> {
  const identity = identityOf(row);
  const key = compat(row);
  const line = ctx.held.directions.get(key);
  if (!identity || !line || typeof line.text !== 'string') {
    await saveIntent(ctx, row);
    return;
  }
  const input = readInput(ctx, identity, row);
  if (!input) return;
  const changes = intentChanges(input);
  if (changes.any || changes.chosen) {
    await saveIntent(ctx, row);
    const after = readInput(ctx, identity, liveRow(ctx, identity) ?? row);
    if (!after || intentUnsaved(after) || directionLinesQuestion(ctx.held, row)) return;
  }
  await saveDirection(ctx, liveRow(ctx, identity) ?? row);
}

/* Each Keep press is a new outcome to announce, even the same sentence again: its guard goes, and a region
   still holding the last Keep sentence is emptied now, so the press's write is a change the reader's software
   reads rather than the same text set twice. */
function keepUnsay(ctx: Ctx, key: string): void {
  ctx.shell.announcer.forget(`keep:${key}`);
}

/* Leave it: settle every later direction the reader was shown, adopting the draft in the same write. Every
   press names the revision the list was drawn against, and goes to `/api/annotate`, which settles and reads
   nothing: it never carries Allow. Analyze drift is its own press beside it, so a model is never started by
   settling. */
export async function keepIntent(ctx: Ctx, row: Row, projectKey: string): Promise<void> {
  const identity = identityOf(row);
  if (!identity) return;
  const key = compat(row);
  const control = `direction-keep:${key}`;
  if (pendingHas(ctx, control) || ctx.held.requests.get(key)?.pending) return;
  const input = readInput(ctx, identity, row);
  if (!input) return;
  const pending = directionsOpen(input, sourceOf(ctx, input, projectKey));
  if (!pending.length) return;
  keepUnsay(ctx, key);
  startFeedback(ctx, control);
  if (intentUnsaved(input)) {
    const edited = editedRefusal(pendingHas(ctx, `${intentKey(row)}:save`));
    ctx.held.requests.set(key, {
      ...ctx.held.requests.get(key),
      pending: false,
      message: edited,
      refusal: true,
      announced: true,
    });
    announce(ctx, `keep:${key}`, edited);
    ctx.held.notify();
    return;
  }
  const draft = intentDraft(input);
  const last = pending[pending.length - 1];
  const through = nextNumber(last?.at);
  const adopt = adoption(draft);
  const annotation = input.annotation;
  const drawnAt = nextNumber(annotation?.['revision']) || 0;
  const press = pendingStart(ctx, control, 'Keeping…', 'Keeping your intent.');
  if (!press) return;
  const previousNotice = ctx.held.requests.get(key)?.notice;
  const request = {
    ...(previousNotice !== undefined ? { notice: previousNotice } : {}),
    pending: true,
    message: '',
    adoption: adopt,
    announced: true,
  } as {
    pending: boolean;
    message: string;
    adoption: Record<string, unknown>;
    announced: boolean;
    notice?: Readonly<Record<string, unknown>> | null;
  };
  ctx.held.requests.set(key, request);
  ctx.held.notify();
  try {
    const read = await readWhole(ctx, identity, row, pending, drawnAt, press.signal);
    if (read.kind !== 'read') {
      request.message = read.kind === 'refused' ? (read.message ?? KEEP_UNOPENED) : KEEP_READ_FIRST;
      return;
    }
    /* A press after the list was drawn names the revision it was drawn against, so words saved since then
       are refused rather than settled over. `pending` is every drawn direction here, so `through` is too. */
    const reply = answered(
      await ctx.shell.runtime.client.postAnnotate(
        { ...identity, ...adopt, settle_through: through, expected_revision: drawnAt },
        press.signal,
      ),
    );
    const body = reply.kind === 'answered' && reply.ok ? reply.body : null;
    if (!body || body.ok !== true) throw new Error('not kept');
    const outcome = String(body.outcome || '');
    const settled = ['stored', 'unchanged'].includes(outcome) && body.persisted !== false;
    request.message = settled
      ? keptDirections(pending.length)
      : outcome === 'untrusted'
        ? (HELD_CUES['settle-untrusted'] ?? KEEP_REFUSED)
        : KEEP_REFUSED;
    if (settled) {
      forgetAdopted(ctx, row, draft);
    }
    await refresh(ctx);
  } catch {
    request.message = KEEP_UNCONFIRMED;
  } finally {
    request.pending = false;
    pendingEnd(ctx, control, press);
    /* The persistent polite region, and only there: the paragraph beside the control is drawn without a
       role, so the outcome is announced once. */
    if (request.message) {
      ctx.held.actionFeedback.set(control, request.message);
      announce(ctx, `keep:${key}`, request.message);
    }
    ctx.held.notify();
    if (request.message === KEEP_READ_FIRST) ctx.held.requestFocus(`direction-whole:${key}`);
  }
}
