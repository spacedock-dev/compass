import { nextNumber } from '../api/bootstrap';
import { compatSessKey } from '../api/identity';
import { clock as clockText, isRecord, type Row } from '../observed';
import {
  openedWithControl,
  promptCandidate,
  PROMPT_CHOSEN,
  PROMPT_SOURCES,
  type PromptCandidate,
} from '../sessions/intent';
import type { ContextEntry } from '../store/board';
import {
  annotateOn,
  annotationDiscarded,
  annotationLines,
  storeUnreadable,
  OUTCOME_LINES_MAX,
  type Annotation,
} from './annotation';
import type { Held, PromptChoice } from './held';
import {
  ADOPT_CHANGED,
  ADOPT_REFUSED,
  ANALYZE_READS_PROMPT,
  DIRECTION_CLIPPED,
  EXCERPT_READ_WHOLE,
  INTENT_EDITED,
  INTENT_EDITED_ADD,
  INTENT_SAVING,
  LINES_FULL,
  directionTooLong,
} from './sentences';
import { conflictCandidates, entryNumbers, type WorkEntry, type WorkSource } from './work';

/* What the Intent panel derives from the payload and from what the reader holds, as pure functions. Each
   one reads a `Held` and never writes it: the legacy page deleted a held choice from inside the function
   that asked for the draft, and a render that writes is a render that cannot be repeated, so the deletion
   is `reconcileChosen`, run once after a render by the panel. */

export { PROMPT_CHOSEN, PROMPT_SOURCES };

export function heldKey(session: Row | null | undefined, kind: string): string {
  return `held:${String(session?.['harness'] || '')}:${String(session?.['sid'] || '')}:${kind}`;
}

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
  return Boolean(chosenCandidate(held, contexts, session)) || choicesSettled(contexts, session);
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
  if (String(savedGoal(input) || '').trim()) return null;
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

export function chosenOverSaved(input: DraftInput): boolean {
  const draft = intentDraft(input);
  return (
    Boolean(draft) &&
    draft?.source === PROMPT_CHOSEN &&
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
  if (typed !== undefined) {
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
    undoable: typed !== baseline || lines || pending,
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

/* Why the goal box arrives empty over a session that opened with a harness command: the command's name
   alone, since its arguments are not the reader's goal either. */
export function noDraftWhy(session: Row, annotation: Annotation | null, payload: Row): string {
  if (!annotateOn(payload) || storeUnreadable(payload)) return '';
  const goal = annotation ? annotation['goal'] : session['annotation_goal'];
  if (String(goal || '').trim() || !openedWithControl(session)) return '';
  const command = String(session['first_prompt'] || '')
    .trim()
    .split(/\s+/)[0];
  return command
    ? `This session opened with ${command}, so there is no first prompt to draft a goal from.`
    : '';
}

/* Where a saved line came from, named by the entry itself: "added from #12" where the list numbers it,
   "added from your direction at 14:04" where it does not. With no record read, or the entry gone from it,
   the kind of source alone. */
export function lineSource(
  line: { readonly source: string; readonly sourceId: string } | null,
  session: Row,
  source: Pick<WorkSource, 'state' | 'all' | 'entries'> | null,
  payload: Row,
): string {
  const kind = line?.source === 'entry' ? 'added from an entry' : 'typed';
  if (!line || line.source !== 'entry' || !line.sourceId) return kind;
  if (!source || (source.state !== 'read' && source.state !== 'empty')) return kind;
  const n = entryNumbers(session, source, payload).get(line.sourceId);
  if (n !== undefined) return `added from #${String(n)}`;
  const entry = (source.all || source.entries || []).find(
    (item) => String(item.id || '') === line.sourceId,
  );
  const at = entry ? nextNumber(entry.at) : null;
  return at !== null && at > 0 ? `added from your direction at ${clockText(at)}` : kind;
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
  if (draft && draft.source === PROMPT_CHOSEN) return INTENT_EDITED_ADD;
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
  if (!choices.length && !((candidate?.at ?? 0) > 0) && !listed) {
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
  const options = choices.map((choice) => {
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
      selected: holds && chosen?.factId === choice.factId,
    };
  });
  return {
    visible: true,
    pending: held.prompts.get(compatSessKey(session))?.pending === true,
    failed: held.prompts.get(compatSessKey(session))?.failed === true,
    options,
    value: options.find((option) => option.selected)?.value ?? '',
  };
}

export const DRAFT_FIRST_UNSAVED = 'Draft from your first prompt, not saved';
export const DRAFT_LATEST_UNSAVED = 'Draft from your latest prompt, not saved';

export type IntentStatus =
  | 'Saving…'
  | 'Not confirmed'
  | 'Not saved'
  | 'Unsaved changes'
  | typeof DRAFT_FIRST_UNSAVED
  | typeof DRAFT_LATEST_UNSAVED
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
  const changes = intentChanges(input);
  /* Only what Save intent would write. An undoable-only box (a draft emptied over a goal-less session, or the
     stored goal typed back over a choice) writes nothing, and "Unsaved changes" beside an inert Save misled. */
  if (changes.any || changes.chosen) return 'Unsaved changes';
  /* A goal drafted from the prompt is Compass's suggestion, not an edit: "Unsaved changes" on opening a
     session, before the reader typed anything, read as work of theirs at risk (usability review,
     2026-10-20). It still says it is not saved, because Save intent is what adopts it. */
  if (changes.adoptable) {
    const drafted = intentDraft(input);
    if (drafted?.source === 'first-prompt') return DRAFT_FIRST_UNSAVED;
    if (drafted?.source === 'latest-prompt') return DRAFT_LATEST_UNSAVED;
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

/* Goal source line under the textarea: one honest state derived from the annotation and held draft. */
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
  if (drafted && text === drafted.text) {
    const at = nextNumber(drafted.at);
    const which =
      drafted.source === 'first-prompt'
        ? 'first'
        : drafted.source === 'latest-prompt'
          ? 'latest'
          : at !== null && at > 0
            ? clockText(at)
            : 'chosen';
    const clipped = drafted.cut === true || drafted.text.endsWith('…');
    return `From your prompt · ${which} · not saved. ${ANALYZE_READS_PROMPT}${clipped ? ` ${EXCERPT_READ_WHOLE}` : ''}`;
  }
  const savedFromPrompt =
    !discarded && PROMPT_SOURCES.includes(String(annotation?.['goal_source'] || ''));
  const origin = held.chosen.get(key)?.text ?? drafted?.text ?? (savedFromPrompt ? stored : '');
  /* By overlap and not by history alone: words typed over a selected-all prompt replace it in one change
     event, never pass through an empty box, and are the reader's own. */
  const startedFromPrompt = !held.cleared.has(key) && sharesWords(text, origin);
  if (held.goals.has(key) && text !== stored) {
    return startedFromPrompt ? 'From your prompt, edited · not saved' : 'Typed · not saved';
  }
  if (stored.trim()) {
    if (savedFromPrompt) {
      const source = annotation?.['goal_source'];
      const at = nextNumber(annotation?.['goal_source_at']);
      const which =
        source === 'first-prompt'
          ? 'first'
          : source === 'latest-prompt'
            ? 'latest'
            : at !== null && at > 0
              ? clockText(at)
              : 'chosen';
      /* No time: the store publishes `goal_saved_at` only for typed words, and the revision's `at` moves on a
         lines-only save, so it would restamp an adoption that did not change. */
      const clipped = stored.endsWith('…') ? `. ${EXCERPT_READ_WHOLE}` : '';
      return `From your prompt · ${which} · saved${clipped}`;
    }
    const savedAt = nextNumber(annotation?.['goal_saved_at']) ?? nextNumber(annotation?.['at']);
    return `Typed · ${savedAt !== null && savedAt > 0 ? `saved ${clockText(savedAt)}` : 'saved'}`;
  }
  return '';
}
