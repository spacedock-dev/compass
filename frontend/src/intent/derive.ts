import { nextNumber } from '../api/bootstrap';
import { compatSessKey } from '../api/identity';
import { clock as clockText, isRecord, type Row } from '../observed';
import { datedClock } from '../observed/values';
import {
  openedWithControl,
  promptCandidate,
  PROMPT_CHOSEN,
  PROMPT_SOURCES,
  SESSION_GOAL,
  SESSION_GOAL_HARNESSES,
  sessionGoalCandidate,
  type PromptCandidate,
} from '../sessions/intent';
import { GOAL_UNCLEAR_RESULT } from '../drift/sentences';
import type { ContextEntry } from '../store/board';
import {
  annotateOn,
  annotationDiscarded,
  annotationLines,
  goalCap,
  storeUnreadable,
  OUTCOME_LINES_MAX,
  type Annotation,
} from './annotation';
import type { FoundGoal, Held, PromptChoice } from './held';
import {
  ADOPT_CHANGED,
  ADOPT_REFUSED,
  DIRECTION_CLIPPED,
  EXCERPT_READ_WHOLE,
  INTENT_EDITED,
  INTENT_EDITED_ADD,
  INTENT_SAVING,
  LINES_FULL,
  directionTooLong,
  goalCut,
} from './sentences';
import { conflictCandidates, type WorkEntry, type WorkSource } from './work';

/* What the Intent panel derives from the payload and from what the reader holds, as pure functions. Each
   one reads a `Held` and never writes it: the legacy page deleted a held choice from inside the function
   that asked for the draft, and a render that writes is a render that cannot be repeated, so the deletion
   is `reconcileChosen`, run once after a render by the panel. */

export { PROMPT_CHOSEN, PROMPT_SOURCES, SESSION_GOAL };

export function heldKey(session: Row | null | undefined, kind: string): string {
  return `held:${String(session?.['harness'] || '')}:${String(session?.['sid'] || '')}:${kind}`;
}

/* Not a goal source the server knows: a found goal is typed words once saved. It names where the box's words began. */
const FOUND_FROM_PROMPTS = 'found-from-prompts';

export const goalKey = (session: Row): string => heldKey(session, 'goal');
export const linesKey = (session: Row): string => heldKey(session, 'lines');
export const intentKey = (session: Row): string => heldKey(session, 'intent');
export const discardKey = (session: Row): string => heldKey(session, 'discard');

export type Contexts = ReadonlyMap<string, ContextEntry>;

/* The entries of every context whose key ends with this session's, which is how the legacy page found the
   focused context without knowing its project. */
function contextsFor(contexts: Contexts, session: Row): ContextEntry[] {
  const suffix = `\n${compatSessKey(session)}`;
  return [...contexts].filter(([key]) => key.endsWith(suffix)).map(([, entry]) => entry);
}

/* Whether this session's focused context has loaded without error, so a choice it no longer offers was
   withdrawn rather than not yet fetched. */
export function choicesSettled(contexts: Contexts, session: Row): boolean {
  return contextsFor(contexts, session).some((entry) => entry.data && !entry.error);
}

/* The prompts "Use your prompt" offers: the server's own `prompt_choices` on this session's focused project
   context, as `annotations.prompt_choices` built them, and nothing the page derives. An entry without an
   id, a time or words is not offered, because the server would refuse its adoption. Empty until that
   context has loaded. */
export function promptChoices(held: Held, contexts: Contexts, session: Row): PromptChoice[] {
  const menu = held.prompts.get(compatSessKey(session));
  const usable = (choice: PromptChoice): boolean =>
    typeof choice.factId === 'string' &&
    Boolean(choice.factId) &&
    typeof choice.text === 'string' &&
    Boolean(choice.text.trim()) &&
    (nextNumber(choice.at) || 0) > 0;
  if (menu && Array.isArray(menu.choices)) return menu.choices.filter(usable);
  for (const entry of contextsFor(contexts, session)) {
    const choices = (entry.data as unknown as Row | null)?.['prompt_choices'];
    if (!Array.isArray(choices)) continue;
    return choices
      .filter(isRecord)
      .map(
        (choice): PromptChoice => ({
          factId: typeof choice['fact_id'] === 'string' ? choice['fact_id'] : '',
          text: typeof choice['text'] === 'string' ? choice['text'] : '',
          at: nextNumber(choice['at']),
          cut: choice['cut'] === true,
        }),
      )
      .filter(usable);
  }
  return [];
}

export interface Draft extends PromptCandidate {
  readonly factId?: string;
  readonly cut?: boolean;
}

/* The chosen prompt as a candidate, only while the server still offers the same words at the same time
   under that fact: the adoption names all three, and a changed record must not adopt new words under an
   old choice. A direction used as the goal was never in the menu, so it stands as held. */
export function chosenCandidate(held: Held, contexts: Contexts, session: Row): Draft | null {
  if (!['claude', 'codex'].includes(String(session['harness']))) return null;
  const choice = held.chosen.get(goalKey(session));
  if (!choice) return null;
  if (choice.source === SESSION_GOAL) {
    /* Only while the row still states the same words at the same time: a /goal that changed or was cleared
       since is not what the reader chose. */
    const stated = sessionGoalCandidate(session);
    return stated && stated.text === choice.text && stated.at === choice.at ? stated : null;
  }
  const found = choice.direction
    ? choice
    : promptChoices(held, contexts, session).find(
        (offered) =>
          offered.factId === choice.factId &&
          offered.text === choice.text &&
          offered.at === choice.at,
      );
  return found
    ? {
        text: found.text,
        at: found.at,
        source: PROMPT_CHOSEN,
        factId: found.factId,
        cut: found.cut === true,
      }
    : null;
}

export interface DraftInput {
  readonly held: Held;
  readonly contexts: Contexts;
  readonly payload: Row;
  readonly session: Row;
  readonly annotation: Annotation | null;
}

function savedGoal(input: DraftInput): unknown {
  return input.annotation ? input.annotation['goal'] : input.session['annotation_goal'];
}

export interface GoalUpdate {
  readonly text: string;
  readonly at: number;
  readonly cut: boolean;
}

const firstMoment = (...values: unknown[]): number | null => {
  for (const value of values) {
    const moment = nextNumber(value);
    if (moment !== null && moment > 0) return moment;
  }
  return null;
};

/* A /goal the session set after the reader's saved goal, offered as an update and never written over their
   words. "After" is the moment the saved words stand at, as the later-direction floor reads it
   (`annotations.direction_floor`): an adopted goal by its source's time, typed words by when they were
   saved. Nothing is offered over a goal-less or discarded session, where the /goal is the draft itself, over
   the same words, over one the reader already took, or over one they declined at this time or later. */
export function goalUpdate(input: DraftInput): GoalUpdate | null {
  const { held, session, annotation, payload } = input;
  if (!annotateOn(payload) || storeUnreadable(payload)) return null;
  const stated = sessionGoalCandidate(session);
  if (!stated || stated.at === null || annotationDiscarded(annotation)) return null;
  const stored = String(savedGoal(input) || '').trim();
  if (!stored || stored === stated.text) return null;
  const savedAt = firstMoment(
    annotation?.['goal_source_at'],
    annotation?.['goal_saved_at'],
    annotation?.['at'],
  );
  if (savedAt === null || stated.at <= savedAt) return null;
  const key = goalKey(session);
  if (held.chosen.get(key)?.source === SESSION_GOAL) return null;
  if ((held.kept.get(key) ?? 0) >= stated.at) return null;
  return { text: stated.text, at: stated.at, cut: stated.cut };
}

/* Whether a held choice no longer stands: its words are now the saved goal, or the server stopped offering
   it. The legacy page dropped it from inside the draft read; here the read treats it as absent and the
   panel drops it afterwards. */
export function chosenStands(input: DraftInput): Draft | null {
  const { held, contexts, session, annotation } = input;
  const choice = held.chosen.get(goalKey(session));
  if (!choice) return null;
  const chosen = chosenCandidate(held, contexts, session);
  const sourceChanged =
    choice.direction &&
    (annotation?.['goal_source'] !== PROMPT_CHOSEN ||
      nextNumber(annotation?.['goal_source_at']) !== (chosen?.at ?? null));
  if (chosen && (String(savedGoal(input) || '').trim() !== chosen.text || sourceChanged))
    return chosen;
  return null;
}

export function chosenIsStale(input: DraftInput): boolean {
  const { held, contexts, session, payload } = input;
  // The legacy read dropped it only past the same gate the draft has: with the store off or unreadable it
  // left the choice alone.
  if (!annotateOn(payload) || storeUnreadable(payload)) return false;
  if (!held.chosen.has(goalKey(session))) return false;
  if (chosenStands(input)) return false;
  // A /goal choice is checked against the row itself, so it needs no settled menu to be known gone.
  if (held.chosen.get(goalKey(session))?.source === SESSION_GOAL) return true;
  return Boolean(chosenCandidate(held, contexts, session)) || choicesSettled(contexts, session);
}

/* The goal a "Find goal" press found in the reader's prompts, while it stands. The order the owner ruled is the
   reader's saved goal, then a /goal, then this, then today's drafts, so it stands only where none of the first
   two exists. It was written into the box as the reader's pending words, and it stands only while the box still
   holds exactly those words: an edit replaces it, and the same words typed back are the same words. Derived on
   every render and never written. */
export function foundGoal(input: DraftInput): FoundGoal | null {
  const { held, payload, session } = input;
  if (!annotateOn(payload) || storeUnreadable(payload)) return null;
  const found = held.found.get(compatSessKey(session));
  if (!found) return null;
  if (String(savedGoal(input) || '').trim()) return null;
  if (sessionGoalCandidate(session)) return null;
  return held.goals.get(goalKey(session)) === found.text ? found : null;
}

/* Whether "Find goal" is offered: while the reader has saved no goal, the session set no /goal, and no found
   goal is in the box, on a harness whose prompts Compass reads. The press is the reader's own, so this says only
   whether the control is drawn and whether a press is taken. */
export function findGoalOffered(input: DraftInput): boolean {
  const { payload, session } = input;
  if (!annotateOn(payload) || storeUnreadable(payload)) return false;
  if (!['claude', 'codex'].includes(String(session['harness']))) return false;
  if (String(savedGoal(input) || '').trim()) return false;
  if (sessionGoalCandidate(session)) return false;
  return foundGoal(input) === null;
}

/* The goal a goal-less session arrives with: the first prompt as Compass publishes it, or the latest where
   no first prompt with a time is published, and null where neither can be adopted. Derived from the payload
   on every render and never written, so it holds no reader state; the box's own edits ride the held draft.
   Nothing is drafted over a store this build cannot read, where Save intent could not save. A prompt chosen
   from "Use your prompt" stands first, over a saved goal as well: the reader picked it, so it is the
   pending adoption every consumer of the draft reads. */
export function intentDraft(input: DraftInput): Draft | null {
  const { payload, session } = input;
  if (!annotateOn(payload) || storeUnreadable(payload)) return null;
  const chosen = chosenStands(input);
  if (chosen) return chosen;
  /* A discarded session starts empty: the draft is offered by "Use your prompt" and never put back in the
     box, because one stray Save intent would restore an intent the reader had just deleted. */
  if (annotationDiscarded(input.annotation)) return null;
  if (String(savedGoal(input) || '').trim()) return null;
  /* The goal the session set with /goal is the working goal until the reader edits it. It comes first, and
     ahead of the control check below: a session that opened with `/goal` has no first prompt to draft, and
     its /goal is the goal it was given. */
  const stated = sessionGoalCandidate(session);
  if (stated) return stated;
  /* A session that opened with a harness control has no first prompt to draft, and the latest is a later
     record, which the first-prompt read never drafts from. */
  if (openedWithControl(session)) return null;
  for (const source of ['first-prompt', 'latest-prompt'] as const) {
    const candidate = promptCandidate(session, source);
    if (candidate && candidate.at !== null) return candidate;
  }
  return null;
}

/* What the goal box is compared against: the drafted prompt over a goal-less session, where the draft
   stands in the stored words' place, and the stored goal otherwise. `save` compares the box against it, so
   the untouched draft adopts the draft rather than typing an excerpt. */
export function goalBaseline(input: DraftInput): string {
  const drafted = intentDraft(input);
  return drafted ? drafted.text : String(input.annotation?.['goal'] || '');
}

/* Whether the stored reading refused the saved goal as too vague to analyze against. Read from the stored
   reading itself, not from the level: the level is recomputed per collection and only a loaded context
   carries it. The refusal is about the words it read, so it holds only while the reading is of the revision
   saved now; a new save, however small, is a new goal, and the reader editing the box clears it where it is
   drawn (`GoalField`). */
export function goalRefused(input: DraftInput): boolean {
  const annotation = input.annotation;
  if (!annotation || storeUnreadable(input.payload) || annotation['not_accurate'] === true) {
    return false;
  }
  const raw = annotation['assessment'];
  if (!isRecord(raw)) return false;
  const read = nextNumber(raw['revision_read']);
  if (read === null || read !== nextNumber(annotation['revision'])) return false;
  const criteria = raw['criteria'];
  const goal = isRecord(criteria) ? criteria['goal'] : null;
  return isRecord(goal) && goal['result'] === GOAL_UNCLEAR_RESULT;
}

export function chosenOverSaved(input: DraftInput): boolean {
  /* `chosenStands` is what `intentDraft` returns first, so a draft it returns is the reader's pick. */
  return (
    intentDraft(input) !== null &&
    chosenStands(input) !== null &&
    Boolean(String(savedGoal(input) || '').trim())
  );
}

/* Whether the draft is a prompt adoption the reader has not saved and the live estimate must not be drawn
   over: a chosen prompt over saved words is a pending change, not a goal-less draft. */
export function intentDrafted(input: DraftInput): boolean {
  return Boolean(intentDraft(input)) && !chosenOverSaved(input);
}

/* The expected outcome, as a checklist of up to six lines. One draft per session, an array held beside the
   goal's, so adding, removing and typing survive a redraw as the goal's draft does. */
export function savedLines(annotation: Annotation | null | undefined): string[] {
  return annotationLines(annotation).map((line) => line.text);
}

export function linesDraft(held: Held, session: Row, annotation: Annotation | null): string[] {
  const draft = held.lines.get(linesKey(session));
  return draft ? draft.slice() : savedLines(annotation);
}

/* What a save would send: the lines with words in them, in order. */
export function linesToSend(draft: readonly string[]): string[] {
  return draft.filter((text) => String(text || '').trim());
}

export function linesChanged(draft: readonly string[], annotation: Annotation | null): boolean {
  return JSON.stringify(linesToSend(draft)) !== JSON.stringify(savedLines(annotation));
}

export function linesOrigins(held: Held, key: string, draft: readonly string[]): (number | null)[] {
  const kept = held.origins.get(key);
  return kept && kept.length === draft.length ? kept.slice() : draft.map((_text, index) => index);
}

/* Whether a press would stand on words other than the ones on screen: the goal box differs from what it
   stands on (the draft, or the saved goal), or the outcome-lines draft differs from what the server holds.
   A box put back to those words is not an edit. Keep, Add's save and Analyze are refused over one. */
export function intentUnsaved(input: DraftInput): boolean {
  const { held, session, annotation } = input;
  /* `/api/reading` refuses an implicit adoption over a saved goal, so a prompt chosen over one waits for its
     save as a typed edit does. */
  if (chosenOverSaved(input)) return true;
  const typed = held.goals.get(goalKey(session));
  /* A found goal standing in the box is the working goal, as a /goal is: it is not an edit, so a reading may
     start on it (the press saves it first, as typed words). */
  if (typed !== undefined && !foundGoal(input)) {
    const draft = intentDraft(input);
    const stands = draft ? draft.text : String(savedGoal(input) || '');
    if (typed !== stands) return true;
  }
  const lines = held.lines.get(linesKey(session));
  return lines !== undefined && linesChanged(lines, annotation);
}

export interface Changes {
  readonly goal: boolean;
  readonly lines: boolean;
  readonly typed: string;
  readonly chosen: boolean;
  readonly pending: boolean;
  readonly adoptable: boolean;
  readonly any: boolean;
  readonly undoable: boolean;
}

/* The one save for both fields, and what it would write. The goal counts as changed where its box has left
   the stored words and is not back at the draft, which Save intent adopts; the lines where the list to send
   differs from the stored list. `undoable` is wider: a box emptied over a draft writes nothing, and is still
   the reader's edit to put back. */
export function intentChanges(input: DraftInput): Changes {
  const { held, session, annotation } = input;
  const key = goalKey(session);
  const baseline = goalBaseline(input);
  const stored = String(annotation?.['goal'] || '');
  const typed = held.goals.has(key) ? (held.goals.get(key) ?? baseline) : baseline;
  const goal = typed !== baseline && typed !== stored;
  const lines = linesChanged(linesDraft(held, session, annotation), annotation);
  /* A prompt chosen from the menu is a change the box shows and the store does not hold, so Save intent
     adopts it, over saved words or an empty goal alike. */
  const chosen = typed === baseline && chosenOverSaved(input);
  const pending =
    typed === baseline &&
    held.chosen.has(key) &&
    Boolean(chosenCandidate(held, input.contexts, session));
  /* An untouched draft is not an edit, so Undo has nothing to undo, but Save intent adopts it: the one
     way to save it. */
  const adoptable = typed === baseline && Boolean(intentDraft(input));
  return {
    goal,
    lines,
    typed,
    chosen,
    pending,
    adoptable,
    any: goal || lines || pending,
    // A found goal is not the reader's edit, so Undo has nothing to put back.
    undoable: (typed !== baseline && !foundGoal(input)) || lines || pending,
  };
}

/* Whether "Keep your standing outcome lines with this goal?" is still unanswered: a direction used as the goal
   asks it once, and Save intent waits for the answer. */
export function directionLinesQuestion(held: Held, session: Row): boolean {
  const choice = held.chosen.get(goalKey(session));
  return Boolean(choice && choice.direction && (choice.linesAnswer ?? null) === null);
}

/* The refusal an unsaved edit earns, and the sentence while Save intent is itself being answered: telling
   the reader to save their intent is false when they just did. */
export function editedRefusal(saving: boolean): string {
  return saving ? INTENT_SAVING : INTENT_EDITED;
}

/* The adoption a request carries: the source, the prompt as drafted and its time, and the fact it came from
   where it came from one. */
export function adoption(draft: Draft | null): Record<string, unknown> {
  return draft
    ? {
        adopt: draft.source,
        expected_prompt: draft.text,
        expected_prompt_at: draft.at,
        ...(draft.factId ? { prompt_fact: draft.factId } : {}),
      }
    : {};
}

/* What a /goal did to the one before it, from the row alone. The earlier goal's words are never published, so
   none are said; a value this build does not know says nothing. */
const EARLIER_GOAL: Readonly<Record<string, (clock: string) => string>> = {
  replaced: (clock) => `Replaced an earlier /goal at ${clock}`,
  met: (clock) => `An earlier /goal was met at ${clock}`,
  'gave-up': (clock) => `Claude Code gave up on an earlier /goal at ${clock}`,
};

function goalClearedAt(session: Row): number | null {
  if (
    !SESSION_GOAL_HARNESSES.includes(String(session['harness'])) ||
    isRecord(session['session_goal'])
  )
    return null;
  const cleared = session['session_goal_cleared'];
  return isRecord(cleared) ? firstMoment(cleared['at']) : null;
}

/* The one line above the Goal field about how an earlier /goal ended, or ''. A clear that left no goal reads
   here unless the session opened with /goal, where the "opened with /goal" sentence already carries it. It
   does not name the draft: the source line directly under it does. Never beside the update offer, which
   already says the /goal changed. */
export function goalEndedNote(input: DraftInput): string {
  const { session, annotation, payload } = input;
  if (goalUpdate(input)) return '';
  const stated = session['session_goal'];
  if (isRecord(stated)) {
    const earlier = stated['earlier'];
    const say = isRecord(earlier) ? EARLIER_GOAL[String(earlier['how'])] : undefined;
    const at = isRecord(earlier) ? firstMoment(earlier['at']) : null;
    return say && at !== null ? say(datedClock(at)) : '';
  }
  const cleared = goalClearedAt(session);
  /* The sentence is drawn only over a box with no draft (IntentSection), so a chosen prompt that hides it
     leaves the clear to this note. */
  if (cleared === null || (!intentDrafted(input) && noDraftWhy(session, annotation, payload)))
    return '';
  return `Your /goal was cleared at ${datedClock(cleared)}`;
}

/* Why the goal box arrives empty over a session that opened with a harness command: the command's name
   alone, since its arguments are not the reader's goal either. */
export function noDraftWhy(session: Row, annotation: Annotation | null, payload: Row): string {
  if (!annotateOn(payload) || storeUnreadable(payload)) return '';
  const goal = annotation ? annotation['goal'] : session['annotation_goal'];
  if (String(goal || '').trim() || !openedWithControl(session)) return '';
  const command = String(session['first_prompt'] || '')
    .trim()
    .split(/\s+/)[0];
  if (!command) return '';
  const stated = session['session_goal'];
  const held = String((isRecord(stated) && stated['text']) || '').trim();
  const cleared = goalClearedAt(session);
  const lead = `This session opened with ${command}, so there is no first prompt to draft a goal from.${
    cleared === null ? '' : ` Your /goal was cleared at ${datedClock(cleared)}.`
  }`;
  /* The session's own /goal is not a draft, but a reader told only "no first prompt" would take the
     session for goal-less. */
  return held ? `${lead} It holds this /goal: ${held}` : lead;
}

/* Where a saved line came from, named by when the reader said it: "added from your 14:04 message". An entry
   number is not used, because the reader may never have been shown the list that numbers it. With no record
   read, or the entry gone from it, the kind of source alone. */
export function lineSource(
  line: { readonly source: string; readonly sourceId: string } | null,
  source: Pick<WorkSource, 'state' | 'all' | 'entries'> | null,
): string {
  const kind = line?.source === 'entry' ? 'added from an entry' : 'typed';
  if (!line || line.source !== 'entry' || !line.sourceId) return kind;
  if (!source || (source.state !== 'read' && source.state !== 'empty')) return kind;
  const entry = (source.all || source.entries || []).find(
    (item) => String(item.id || '') === line.sourceId,
  );
  const at = entry ? nextNumber(entry.at) : null;
  return at !== null && at > 0 ? `added from your ${datedClock(at)} message` : kind;
}

/* The later directions the question asks about, or none: only over words or a draft, and only from a record
   that was read. */
export function directionsOpen(
  input: DraftInput,
  source: Pick<WorkSource, 'state' | 'all' | 'entries'> | null,
): WorkEntry[] {
  if (!annotateOn(input.payload)) return [];
  if (!source || (source.state !== 'read' && source.state !== 'empty')) return [];
  return conflictCandidates(
    input.annotation,
    source.all || source.entries,
    input.session,
    intentDraft(input),
  );
}

/* The selected later direction: the reader's pick while it is still listed, and the newest otherwise. */
export function directionSelected(
  held: Held,
  session: Row,
  pending: readonly WorkEntry[],
): WorkEntry | undefined {
  const pick = held.picks.get(compatSessKey(session));
  return pending.find((entry) => entry.id === pick) ?? pending[pending.length - 1];
}

/* Why the pending line cannot be saved as it stands, or "". An unsaved edit to the intent is one: the save
   would write the added line over words that are not on screen, and then drop the edit. Said here, beside
   the line the reader pressed save on, not in the Drift control. */
export function directionWhy(
  line: { readonly text?: string | undefined; readonly replace?: number | null | undefined },
  input: DraftInput | null,
  cap: number,
): string {
  if (String(line.text || '').length > cap) return directionTooLong(cap);
  const annotation = input?.annotation ?? null;
  if (annotationLines(annotation).length >= OUTCOME_LINES_MAX && (line.replace ?? null) === null) {
    return LINES_FULL;
  }
  if (input && intentUnsaved(input)) return INTENT_EDITED_ADD;
  /* `add_direction` adopts only the first or latest prompt, so over a chosen one the save would be
     refused; the reader saves the choice first. */
  const draft = input ? intentDraft(input) : null;
  if (draft && input && chosenStands(input) !== null) return INTENT_EDITED_ADD;
  return '';
}

export { DIRECTION_CLIPPED };

/* An option's words, cut at the last space at or before `limit` characters. The box receives the whole
   prompt; only the list's line is short. */
export function promptClip(text: unknown, limit: number): string {
  const words = String(text || '');
  if (words.length <= limit) return words;
  const space = words.lastIndexOf(' ', limit);
  return `${(space > 0 ? words.slice(0, space) : words.slice(0, limit)).trimEnd()}…`;
}

export interface PromptMenu {
  /** The prompt choice is drawn at all: only where something could fill it. */
  readonly visible: boolean;
  readonly pending: boolean;
  /** The last read of the reader's prompts failed, which is not the same as finding none. */
  readonly failed: boolean;
  readonly options: readonly {
    readonly value: string;
    readonly label: string;
    readonly selected: boolean;
  }[];
  /** The value the select shows: the chosen prompt while the box still holds it untouched, else empty. */
  readonly value: string;
}

/* "Use your prompt": a Base UI Select in the goal's label row. Choosing fills the goal as a pending
   adoption. React owns the popup; the display gate holds its anchor during background paints.
   The first entry is the earliest
   prompt the record holds; over a session that opened with a harness control that is not its first prompt,
   so it is named the earliest. An excerpt says so in the option itself. */
export function promptMenu(input: DraftInput): PromptMenu {
  const { held, contexts, payload, session } = input;
  const hidden: PromptMenu = {
    visible: false,
    pending: false,
    failed: false,
    options: [],
    value: '',
  };
  if (!annotateOn(payload) || storeUnreadable(payload)) return hidden;
  if (!['claude', 'codex'].includes(String(session['harness'] || ''))) return hidden;
  const choices = promptChoices(held, contexts, session);
  const candidate =
    promptCandidate(session, 'first-prompt') || promptCandidate(session, 'latest-prompt');
  const listed = contextsFor(contexts, session).some((entry) => {
    const semantic = (entry.data as unknown as Row | null)?.['semantic'];
    const facts = isRecord(semantic) && Array.isArray(semantic['facts']) ? semantic['facts'] : [];
    return facts.some((fact) => {
      if (!isRecord(fact) || fact['type'] !== 'user_message') return false;
      const from = fact['source_session'];
      return (
        isRecord(from) && from['harness'] === session['harness'] && from['sid'] === session['sid']
      );
    });
  });
  const stated = sessionGoalCandidate(session);
  if (!choices.length && !((candidate?.at ?? 0) > 0) && !listed && !stated) {
    /* A popup the reader already opened outlives the offer that showed its trigger, so what the last read
       said (still loading, or failed) must not be lost with the visibility. */
    const read = held.prompts.get(compatSessKey(session));
    return { ...hidden, pending: read?.pending === true, failed: read?.failed === true };
  }
  /* "First" only for the row's own first prompt. The choices come from the focused record, which holds the
     newest 100 events, so in a long session its earliest prompt is a later message. */
  const firstAt = nextNumber(session['first_prompt_at']);
  const earliestAt = Math.min(...choices.map((choice) => choice.at ?? Infinity));
  const latestAt = Math.max(...choices.map((choice) => choice.at ?? -Infinity));
  /* The face shows the pick only while the box still holds it untouched; a keystroke puts it back to the
     placeholder, so the same prompt can be picked again. */
  const key = goalKey(session);
  const chosen = held.chosen.get(key);
  const holds = Boolean(chosen) && (!held.goals.has(key) || held.goals.get(key) === chosen?.text);
  const detected = stated
    ? [
        {
          value: SESSION_GOAL,
          label: `Goal detected · ${clockText(stated.at ?? 0)}${stated.cut ? ' · cut' : ''} — ${promptClip(stated.text, 60)}`,
          selected: holds && chosen?.source === SESSION_GOAL,
        },
      ]
    : [];
  const prompts = choices.map((choice) => {
    const name =
      !openedWithControl(session) &&
      firstAt !== null &&
      choice.at === firstAt &&
      choice.at === earliestAt
        ? 'First prompt'
        : choice.at === earliestAt
          ? 'Earliest prompt'
          : choice.at === latestAt
            ? 'Latest prompt'
            : 'Earlier prompt';
    return {
      value: choice.factId,
      label: `${name} · ${clockText(choice.at ?? 0)}${choice.cut ? ' · excerpt' : ''} — ${promptClip(choice.text, 60)}`,
      selected: holds && chosen?.source !== SESSION_GOAL && chosen?.factId === choice.factId,
    };
  });
  const options = [...detected, ...prompts];
  return {
    visible: true,
    pending: held.prompts.get(compatSessKey(session))?.pending === true,
    failed: held.prompts.get(compatSessKey(session))?.failed === true,
    options,
    value: options.find((option) => option.selected)?.value ?? '',
  };
}

/* One word, as the design's status is. Which prompt the draft came from is the goal's own source line. */
export const DRAFT_UNSAVED = 'Draft';

export type IntentStatus =
  | 'Saving…'
  | 'Not confirmed'
  | 'Not saved'
  | 'Unsaved changes'
  | typeof DRAFT_UNSAVED
  | 'Saved'
  | '';

/* Header status: derived purely from the session's annotation and held state, ranked so a pending save
   never flashes "Saved" and an edit held over a newer board revision still says "Unsaved changes". */
export function intentStatus(
  input: DraftInput,
  pending: readonly string[] | boolean = [],
): IntentStatus {
  if (storeUnreadable(input.payload)) return '';
  const key = intentKey(input.session);
  const saving = typeof pending === 'boolean' ? pending : pending.includes(`${key}:save`);
  if (saving) return 'Saving…';
  const kind = input.held.kind(key);
  if (kind === 'unconfirmed') return 'Not confirmed';
  if (['error', 'unpersisted', 'untrusted', 'unreadable'].includes(kind)) return 'Not saved';
  const requestMessage = input.held.requests.get(compatSessKey(input.session))?.message ?? '';
  if (requestMessage === ADOPT_CHANGED || Object.values(ADOPT_REFUSED).includes(requestMessage)) {
    return 'Not saved';
  }
  /* A goal found in the prompts is used until edited, as a /goal is, and is the same kind of draft. */
  if (foundGoal(input)) return DRAFT_UNSAVED;
  const changes = intentChanges(input);
  /* Only what Save intent would write. An undoable-only box (a draft emptied over a goal-less session, or the
     stored goal typed back over a choice) writes nothing, and "Unsaved changes" beside an inert Save misled. */
  if (changes.any || changes.chosen) return 'Unsaved changes';
  /* A goal drafted from the prompt is Compass's suggestion, not an edit: "Unsaved changes" on opening a
     session, before the reader typed anything, read as work of theirs at risk (usability review,
     2026-10-20). A detected /goal is the same: it is used until edited, and "Unsaved changes" beside a
     disabled Undo changes disagreed about whether the reader had changed anything. It still says it is not
     saved, because Save intent is what adopts it. */
  if (changes.adoptable) {
    const drafted = intentDraft(input);
    if (
      drafted?.source === 'first-prompt' ||
      drafted?.source === 'latest-prompt' ||
      drafted?.source === SESSION_GOAL
    ) {
      return DRAFT_UNSAVED;
    }
    return 'Unsaved changes';
  }
  const discarded = annotationDiscarded(input.annotation);
  const saved =
    !discarded &&
    ((nextNumber(input.annotation?.['revision']) ?? 0) > 0 ||
      Boolean(String(input.annotation?.['goal'] || '').trim()) ||
      annotationLines(input.annotation).length > 0 ||
      kind === 'saved' ||
      kind === 'unchanged');
  return saved ? 'Saved' : '';
}

/* Whether the box still reads as the prompt it started from: at least half of its words appear in that
   prompt. Words of three letters or more, so "a" and "to" shared by any two sentences do not count. */
function sharesWords(text: string, origin: string): boolean {
  if (!origin.trim()) return false;
  const words = (value: string): string[] => value.toLowerCase().match(/[\p{L}\p{N}]+/gu) ?? [];
  const long = (list: string[]): string[] => list.filter((word) => word.length >= 3);
  const typed = long(words(text)).length ? long(words(text)) : words(text);
  if (!typed.length) return false;
  const from = new Set(words(origin));
  return typed.filter((word) => from.has(word)).length * 2 >= typed.length;
}

/* How a source line names the prompt a goal began from. The time a prompt was chosen is no longer shown: the
   line says "the prompt you chose", and the picker beside the box lists the prompts with their times. */
function promptName(source: string): string {
  return source === 'first-prompt'
    ? 'your first prompt'
    : source === 'latest-prompt'
      ? 'your latest prompt'
      : 'the prompt you chose';
}

/* Goal source line above the textarea, under any ended note: one honest state derived from the annotation and held draft. */
export function goalSourceLine(input: DraftInput): string {
  if (storeUnreadable(input.payload)) return '';
  const { held, session, annotation } = input;
  const key = goalKey(session);
  const drafted = intentDraft(input);
  const baseline = goalBaseline(input);
  const discarded = annotationDiscarded(annotation);
  const stored = discarded ? '' : String(annotation?.['goal'] || '');
  const text = held.goals.has(key) ? (held.goals.get(key) ?? baseline) : baseline;
  if (!text.trim()) return '';
  const cut = goalCut(goalCap(input.payload));
  const found = foundGoal(input);
  if (found) return `Found in your prompts at ${clockText(found.foundAt)} · not saved`;
  if (drafted && text === drafted.text) {
    const at = nextNumber(drafted.at);
    if (drafted.source === SESSION_GOAL) {
      const when = at !== null && at > 0 ? ` at ${clockText(at)}` : '';
      return `From your /goal${when} · not saved${drafted.cut === true ? cut : ''}`;
    }
    const clipped = drafted.cut === true || drafted.text.endsWith('…');
    // The prompt-length sentence is under "What is sent", where a reader looks for what Analyze reads.
    return `Drafted from ${promptName(drafted.source)} · not saved${clipped ? EXCERPT_READ_WHOLE : ''}`;
  }
  const savedFromPrompt =
    !discarded && PROMPT_SOURCES.includes(String(annotation?.['goal_source'] || ''));
  /* A goal found in the prompts that the reader has since edited is still where their words began, ahead of the
     prompt the box would otherwise draft from. */
  const foundFrom = held.found.get(compatSessKey(session));
  const origin =
    held.chosen.get(key)?.text ??
    foundFrom?.text ??
    drafted?.text ??
    (savedFromPrompt ? stored : '');
  const chosenFrom = held.chosen.get(key);
  const originSource = chosenFrom
    ? (chosenFrom.source ?? PROMPT_CHOSEN)
    : foundFrom
      ? FOUND_FROM_PROMPTS
      : drafted
        ? drafted.source
        : savedFromPrompt
          ? String(annotation?.['goal_source'] || '')
          : '';
  const named =
    originSource === SESSION_GOAL
      ? 'your /goal'
      : originSource === FOUND_FROM_PROMPTS
        ? 'the goal found in your prompts'
        : promptName(originSource);
  /* By overlap and not by history alone: words typed over a selected-all prompt replace it in one change
     event, never pass through an empty box, and are the reader's own. */
  const startedFromPrompt = !held.cleared.has(key) && sharesWords(text, origin);
  if (held.goals.has(key) && text !== stored) {
    return startedFromPrompt ? `Your edit of ${named} · not saved` : 'You typed this · not saved';
  }
  if (stored.trim()) {
    if (savedFromPrompt) {
      const source = annotation?.['goal_source'];
      const at = nextNumber(annotation?.['goal_source_at']);
      if (source === SESSION_GOAL) {
        /* The saved words are still the cut excerpt while the row states the same /goal at the same time, and
           the annotation does not record the cut, so the row is where it is read from. */
        const stated = sessionGoalCandidate(session);
        const stillCut = stated?.cut === true && stated.text === stored && stated.at === at;
        return `From your /goal${at !== null && at > 0 ? ` at ${clockText(at)}` : ''} · saved${stillCut ? cut : ''}`;
      }
      /* No time: the store publishes `goal_saved_at` only for typed words, and the revision's `at` moves on a
         lines-only save, so it would restamp an adoption that did not change. */
      const clipped = stored.endsWith('…') ? EXCERPT_READ_WHOLE : '';
      return `From ${promptName(String(source))} · saved${clipped}`;
    }
    const savedAt = nextNumber(annotation?.['goal_saved_at']) ?? nextNumber(annotation?.['at']);
    return `You typed this · ${savedAt !== null && savedAt > 0 ? `saved at ${clockText(savedAt)}` : 'saved'}`;
  }
  return '';
}
