import { nextNumber } from '../api/bootstrap';
import { compatSessKey } from '../api/identity';
import { intentKey } from '../intent/derive';
import type { RequestNote } from '../intent/held';
import { endedAt, sessionStop, type Row } from '../observed';
import { CUE_TTL_MS } from '../controls/keyedState';
import { eligibility, pressLine } from './route';
import {
  FLIP_CLOSED,
  FLIP_CLOSED_REVISION,
  FLIP_HOLD_MS,
  FLIP_OPEN_ENDED,
  FLIP_OPEN_LAST_TURN,
  FLIP_OPEN_RUNNING,
  FLIP_SAY_EVERY_MS,
} from './sentences';
import type { DriftCtx, Flip } from './state';

/* No silent flips. Analyze opening at once is honest, so inert to live commits on the render that sees it.
   Closing waits until the inert state has held for two distinct payloads and ten seconds, the activity grace,
   so a session pausing between turns (running, then a stop settling for 8 s, then its last turn) never
   closes the button. A candidate that reverts first says nothing. Only the drawn card is tracked: an entry
   not drawn on the pass before is drawn fresh, saying nothing. The legacy page's `nextReadingFlip` is the
   oracle; its clock, its timers and its payload identity are the shell's clock, the commit's timers and the
   board object the card was drawn from. */

/* Whether a press on this session is still being answered: flips wait for it. */
function frozen(ctx: DriftCtx, session: Row): boolean {
  const key = compatSessKey(session);
  return [`reading:${key}`, `direction-keep:${key}`, `${intentKey(session)}:save`].some((name) =>
    ctx.shell.runtime.pending.has(name),
  );
}

function opened(session: Row): string {
  if (endedAt(session) !== null) return FLIP_OPEN_ENDED;
  if (session['state'] === 'idle' && sessionStop(session)) return FLIP_OPEN_LAST_TURN;
  return FLIP_OPEN_RUNNING;
}

function announceFlip(ctx: DriftCtx, session: Row, flip: Flip, sentence: string): void {
  const key = `flip:${compatSessKey(session)}`;
  flip.saidAt = ctx.shell.clock.now();
  flip.said = sentence;
  flip.owed = '';
  ctx.shell.announcer.forget(key);
  ctx.shell.announcer.announce(key, sentence);
}

/* In view every time; to the region at most once a minute per session, so a session that flaps is not read
   out on every turn. A flip inside the minute is held, never dropped: the newest is said when the minute is
   up, so the region's last word is never a state that has gone. */
function say(ctx: DriftCtx, session: Row, flip: Flip, sentence: string): void {
  const now = ctx.shell.clock.now();
  flip.line = sentence;
  flip.lineAt = now;
  if (flip.saidAt !== null && now - flip.saidAt < FLIP_SAY_EVERY_MS) {
    flip.owed = sentence;
    ctx.drift.want('say', flip.saidAt + FLIP_SAY_EVERY_MS);
    return;
  }
  announceFlip(ctx, session, flip, sentence);
}

/* The held flip, once the minute is up, unless the region already said the state the card now shows: a flip
   that reverted inside the minute owes nothing. */
function settleOwed(ctx: DriftCtx, session: Row, flip: Flip): void {
  if (!flip.owed || flip.saidAt === null) return;
  if (ctx.shell.clock.now() - flip.saidAt < FLIP_SAY_EVERY_MS) return;
  const owed = flip.owed;
  flip.owed = '';
  if (owed !== flip.said) announceFlip(ctx, session, flip, owed);
}

/* A press the reader made learned the state itself, so the card takes it without a line: the press's own
   answer says it. */
export function acknowledgeFlip(ctx: DriftCtx, session: Row, pressable: boolean): void {
  const flip = ctx.drift.flips.get(compatSessKey(session));
  if (flip) {
    flip.shown = pressable;
    flip.candidate = null;
    flip.owed = '';
  }
}

export interface FlipInput {
  readonly session: Row;
  readonly pressable: boolean;
  readonly held: Row | null;
  /** A change another refusal still hides (the model switch, an unsaved edit) is tracked and never said. */
  readonly quiet: boolean;
  /** The board object the card is drawn from: a second distinct one is a second payload. */
  readonly payload: unknown;
  readonly epoch: number;
  readonly request: RequestNote | undefined;
}

/* Whether the drawn card shows Analyze pressable, given whether the board says it is. Also says a committed
   change and records the hold's re-render for the commit to arm. */
export function readingFlip(ctx: DriftCtx, input: FlipInput): Flip {
  const { session, pressable, held, quiet, payload, epoch } = input;
  const { drift } = ctx;
  const key = compatSessKey(session);
  const now = ctx.shell.clock.now();
  let flip = drift.flips.get(key);
  if (!flip || flip.drawn < epoch - 1) {
    flip = {
      shown: pressable,
      candidate: null,
      candidateSince: 0,
      candidateData: null,
      saidAt: flip ? flip.saidAt : null,
      said: flip ? flip.said : '',
      owed: '',
      line: '',
      lineAt: 0,
      drawn: epoch,
    };
    drift.rememberFlip(key, flip);
    return flip;
  }
  flip.drawn = epoch;
  settleOwed(ctx, session, flip);
  if (frozen(ctx, session)) return flip;
  if (pressable === flip.shown) {
    flip.candidate = null;
    drift.want('hold', null);
    return flip;
  }
  if (pressable) {
    flip.shown = true;
    flip.candidate = null;
    drift.want('hold', null);
    if (!quiet) say(ctx, session, flip, opened(session));
    return flip;
  }
  if (flip.candidate !== false) {
    flip.candidate = false;
    flip.candidateSince = now;
    flip.candidateData = payload;
  }
  if (payload === flip.candidateData || now - flip.candidateSince < FLIP_HOLD_MS) {
    /* Armed only while the moment is ahead. Past it, the hold waits for the next payload: re-arming a past
       moment redrew the page back to back while the stream was down. */
    const at = flip.candidateSince + FLIP_HOLD_MS;
    drift.want('hold', at > now ? at : null);
    return flip;
  }
  flip.shown = false;
  flip.candidate = null;
  drift.want('hold', null);
  if (quiet) return flip;
  say(
    ctx,
    session,
    flip,
    held && held['reason'] === 'revision-after-end' ? FLIP_CLOSED_REVISION : FLIP_CLOSED,
  );
  return flip;
}

/* The change line, while it stands, with the one timer that takes it down. */
export function flipLine(ctx: DriftCtx, session: Row): string {
  const flip = ctx.drift.flips.get(compatSessKey(session));
  if (!flip || !flip.line) return '';
  const until = flip.lineAt + CUE_TTL_MS;
  if (ctx.shell.clock.now() >= until) {
    flip.line = '';
    return '';
  }
  ctx.drift.want('line', until);
  return flip.line;
}

/* The next click inside the card takes the change line down. */
export function clearFlipLines(ctx: DriftCtx): void {
  let changed = false;
  for (const flip of ctx.drift.flips.values()) {
    if (flip.line) changed = true;
    flip.line = '';
  }
  if (changed) ctx.drift.notify();
}

export interface Board {
  readonly reason: string;
  readonly pressed: Row | null;
  readonly inert: boolean;
  readonly changed: string;
  readonly settling: boolean;
}

/* The board's half of whether Analyze can be pressed, as the drawn card shows it, for the Analyze control and
   the direction question alike: a card that draws Keep and Add in Analyze's place flipped silently, with no
   hold and no Why. `reason` is the press's refusal with the board's ranked first; the answer's `reason` is
   what to draw. */
export function readingBoard(
  ctx: DriftCtx,
  input: {
    readonly session: Row;
    readonly reason: string;
    /** The refusal with the board's press line left out, for a card still holding a close. */
    readonly heldLive: string;
    readonly payload: unknown;
    readonly epoch: number;
    readonly request: RequestNote | undefined;
  },
): Board {
  const { session, payload, epoch, request } = input;
  let { reason } = input;
  let pressed = eligibility(session, request, ctx.shell.clock.now());
  const refusedByBoard =
    Boolean(pressed) && reason === (pressed ? pressLine(session, pressed) : '');
  /* Only the board's eligibility flips: a refusal the reader's own edit caused is not one. While a close is
     still held, the card draws Analyze live and a press is answered by the handler's refusal. */
  const flip = readingFlip(ctx, {
    session,
    pressable: !refusedByBoard,
    held: pressed,
    quiet: Boolean(input.heldLive),
    payload,
    epoch,
    request,
  });
  if (refusedByBoard && flip.shown) {
    reason = input.heldLive;
    pressed = null;
  }
  const inert = refusedByBoard && !flip.shown;
  const changed = flipLine(ctx, session);
  const settling =
    inert && ['settling', 'stop-settling'].includes(String(pressed?.['reason'] || ''));
  const until = nextNumber(pressed?.['until']);
  ctx.drift.want('until', settling && until !== null ? until * 1000 : null);
  return { reason, pressed, inert, changed, settling };
}
