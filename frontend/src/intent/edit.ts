import { compatSessKey } from '../api/identity';
import { type Row } from '../observed';
import { heldCap, scrub } from './annotation';
import { pendingHas, type Ctx, announce } from './context';
import {
  goalBaseline,
  goalKey,
  intentKey,
  linesDraft,
  linesKey,
  linesOrigins,
  type DraftInput,
} from './derive';
import { INTENT_CHOSEN_SAID, LINES_FULL } from './sentences';
import { OUTCOME_LINES_MAX } from './annotation';

/* The reader's own edits, one function each. Every one changes only what is held, saves nothing and sends
   nothing: a keystroke, a pick, a removed line and an Escape are all drafts until Save intent is pressed.
   Each returns what the box should now say, so the editor can put a scrubbed or capped value back into the
   native node, which is the only time the node is written. */

const cap = (input: DraftInput): number => heldCap(input.payload);

/* The store's own scrub and bound, applied to what was typed: a pasted line break is the one space the
   store would keep, and a box over the server's bound is cut, as the native `maxlength` cuts it. */
function bounded(raw: string, input: DraftInput): string {
  return scrub(raw).slice(0, cap(input));
}

/* A keystroke in the goal box. The goal's own cue goes (the next press is a fresh attempt on different
   words), and so does the footer's save mark. */
export function typeGoal(ctx: Ctx, input: DraftInput, raw: string): string {
  const key = goalKey(input.session);
  const value = bounded(raw, input);
  ctx.held.clearActionFeedback(compatSessKey(input.session));
  if (value === '') ctx.held.cleared.add(key);
  else if (value === goalBaseline(input)) ctx.held.cleared.delete(key);
  ctx.held.goals.set(key, value);
  ctx.held.drop(key);
  ctx.held.drop(intentKey(input.session));
  ctx.held.notify();
  return value;
}

/* A keystroke in one outcome line. A line past the list is created, so a box typed into before the list
   knew it exists still lands in its place. */
export function typeLine(input: DraftInput, index: number, raw: string): string {
  const { held, session, annotation } = input;
  held.clearActionFeedback(compatSessKey(session));
  const key = linesKey(session);
  const value = bounded(raw, input);
  const draft = linesDraft(held, session, annotation);
  const origins = linesOrigins(held, key, draft);
  while (draft.length <= index) {
    draft.push('');
    origins.push(null);
  }
  draft[index] = value;
  held.lines.set(key, draft);
  held.origins.set(key, origins);
  held.drop(key);
  held.drop(intentKey(session));
  held.notify();
  return value;
}

/* Emptying the box is an edit, not a save: the cleared field then differs from the store, so Save intent
   goes live and the reader commits the clearing deliberately. */
export function clearGoal(ctx: Ctx, input: DraftInput): void {
  const key = goalKey(input.session);
  ctx.held.clearActionFeedback(compatSessKey(input.session));
  ctx.held.cleared.add(key);
  ctx.held.goals.set(key, '');
  ctx.held.chosen.delete(key);
  ctx.held.drop(key);
  ctx.held.drop(intentKey(input.session));
  ctx.held.requestFocus(key);
}

/* Escape in the goal box: drop the draft rather than write the saved value back into it, because the
   render reads the store whenever there is no draft, so this is the one place the two cannot disagree. A
   chosen prompt goes with it. Not under a save still being answered: its words stay in the box. */
export function escapeGoal(ctx: Ctx, input: DraftInput): boolean {
  if (pendingHas(ctx, `${intentKey(input.session)}:save`)) return false;
  const key = goalKey(input.session);
  ctx.held.clearActionFeedback(compatSessKey(input.session));
  ctx.held.cleared.delete(key);
  ctx.held.goals.delete(key);
  ctx.held.chosen.delete(key);
  ctx.held.drop(key);
  ctx.held.drop(intentKey(input.session));
  ctx.held.requestFocus(key);
  return true;
}

/* Escape in a line: the whole list goes back to what is saved, added and removed lines included. The draft
   is one array, and dropping it is the one place the render and the store cannot disagree. */
export function escapeLines(ctx: Ctx, input: DraftInput): boolean {
  if (pendingHas(ctx, `${intentKey(input.session)}:save`)) return false;
  const key = linesKey(input.session);
  ctx.held.clearActionFeedback(compatSessKey(input.session));
  ctx.held.lines.delete(key);
  ctx.held.origins.delete(key);
  ctx.held.drop(key);
  ctx.held.drop(intentKey(input.session));
  ctx.held.requestFocus(`${key}:0`);
  return true;
}

/* A new empty outcome line, focused, or the six-line refusal said in place. */
export function addLine(ctx: Ctx, input: DraftInput): void {
  const { held, session, annotation } = input;
  held.clearActionFeedback(compatSessKey(session));
  const key = linesKey(session);
  const draft = linesDraft(held, session, annotation);
  const origins = linesOrigins(held, key, draft);
  if (draft.length >= OUTCOME_LINES_MAX) {
    /* Refused in place: nothing is added, and the sentence beside the control is said aloud, because an
       inert control that goes silent reads as a dead one. */
    announce(ctx, key, LINES_FULL);
    return;
  }
  // An empty list is drawn as one empty box, so adding to it adds the second.
  if (!draft.length) {
    draft.push('');
    origins.push(null);
  }
  draft.push('');
  origins.push(null);
  held.lines.set(key, draft);
  held.origins.set(key, origins);
  held.drop(key);
  held.drop(intentKey(session));
  held.requestFocus(`${key}:${String(Math.max(0, draft.length - 1))}`);
}

export function removeLine(input: DraftInput, index: number): void {
  const { held, session, annotation } = input;
  held.clearActionFeedback(compatSessKey(session));
  const key = linesKey(session);
  const draft = linesDraft(held, session, annotation);
  const origins = linesOrigins(held, key, draft);
  draft.splice(index, 1);
  origins.splice(index, 1);
  held.lines.set(key, draft);
  held.origins.set(key, origins);
  held.drop(key);
  held.drop(intentKey(session));
  held.requestFocus(`${key}:${String(Math.max(0, draft.length - 1))}`);
}

/* Undo changes: what Escape does in each box, for both at once. The drafts are dropped rather than
   overwritten with the saved words. Never under a save still being answered: its words stay in the box. */
export function undoChanges(ctx: Ctx, input: DraftInput): void {
  const { held, session } = input;
  held.clearActionFeedback(compatSessKey(session));
  if (pendingHas(ctx, `${intentKey(session)}:save`)) return;
  held.cleared.delete(goalKey(session));
  held.chosen.delete(goalKey(session));
  held.goals.delete(goalKey(session));
  held.drop(goalKey(session));
  held.lines.delete(linesKey(session));
  held.origins.delete(linesKey(session));
  held.drop(linesKey(session));
  held.drop(intentKey(session));
  held.requestFocus(`${intentKey(session)}:undo`);
}

/* Choosing a prompt fills the box and saves nothing: the choice replaces whatever the box held, as a
   pending adoption the reader then saves, edits or undoes. Focus stays on the select, so arrowing through
   it where each arrow is a change previews each prompt in the box without throwing the reader into it. */
export function choosePrompt(
  ctx: Ctx,
  input: DraftInput,
  factId: string,
  choices: readonly {
    readonly factId: string;
    readonly text: string;
    readonly at: number | null;
  }[],
): void {
  const found = choices.find((choice) => choice.factId === factId);
  if (!found) return;
  const key = goalKey(input.session);
  ctx.held.clearActionFeedback(compatSessKey(input.session));
  ctx.held.cleared.delete(key);
  ctx.held.chosen.set(key, { factId: found.factId, text: found.text, at: found.at });
  ctx.held.goals.delete(key);
  ctx.held.drop(key);
  ctx.held.drop(intentKey(input.session));
  announce(ctx, `${key}:chosen`, INTENT_CHOSEN_SAID);
  ctx.held.requestFocus(`${key}:prompt`);
}

/* The selected later direction, kept for the life of the tab. */
export function pickDirection(ctx: Ctx, session: Row, factId: string): void {
  ctx.held.clearActionFeedback(compatSessKey(session));
  ctx.held.picks.set(compatSessKey(session), factId);
  ctx.held.notify();
}
