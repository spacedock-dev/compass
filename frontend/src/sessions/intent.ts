import { nextNumber } from '../api/bootstrap';
import { isRecord, promptCopied, type Row } from '../observed';

/* The slice of the Intent step's semantics that a session row reads, and nothing the editor owns. The
   Intent step owns the goal box, the adopted-prompt menu and every held draft; a row only has to say what
   goal its cell names and where the words came from. So this module reads the payload and no reader
   state: a prompt the reader picked from the menu and has not saved is the editor's state, and the row
   takes it through `chosen` when the Intent step passes one. Until then a row draws as it does for a
   session with no pending choice, which is every session at load. */

/* The closed goal-source tokens an adopted goal carries, spelt as the server's `reading.PROMPT_SOURCES`
   spells them; the legacy page's test compares the two. */
export const PROMPT_CHOSEN = 'chosen-prompt';
/* The goal a Claude Code or Codex session states itself with `/goal`: the reader typed that command, so it
   reads as their prompt (the same tags, the same baseline at its own time). It is the server's
   `reading.SESSION_GOAL`. */
export const SESSION_GOAL = 'session-goal';
/* The harnesses whose rows publish `session_goal`, as the server's `records.SESSION_GOAL_HARNESSES`. */
export const SESSION_GOAL_HARNESSES: readonly string[] = ['claude', 'codex'];
export const PROMPT_SOURCES: readonly string[] = [
  'latest-prompt',
  'first-prompt',
  PROMPT_CHOSEN,
  SESSION_GOAL,
];

/* `reading.CONSTRAINT_CLAIMS`: what the agent claimed about the work. A contradicted claim is not drift
   from the intent, so it never makes a row say Drift. */
export const READING_CLAIMS = 'claims';
const OUTCOME_LINES_MAX = 6;
const OUTCOME_LINE = /^line_([1-9][0-9]*)$/;

/* Spelt once on each side: the server's `reading.ASSESSMENT_KEYS` carries the same members. A reading
   with a key outside this list is one this build cannot read, and a reading half-read is not shown. */
export const READING_ASSESSMENT_KEYS: readonly string[] = [
  'goal_source',
  'goal_source_at',
  'revision_read',
  'revision_read_at',
  'window_start',
  'read_at',
  'stamp',
  'cutoff',
  'scope',
  'scope_text',
  'ended_at_read',
  'evidence_through',
  'coverage',
  'goal_verdict',
  'criteria',
];

function isOutcomeLine(key: string): boolean {
  const match = OUTCOME_LINE.exec(key);
  return key === 'output' || Boolean(match && Number(match[1]) <= OUTCOME_LINES_MAX);
}

export function readingNamesConstraint(key: string): boolean {
  return key === 'goal' || key === READING_CLAIMS || isOutcomeLine(key);
}

/* The server's verdict, never re-derived here: the first prompt was a harness control, so it is not the
   reader's goal and a row drafts nothing from it. */
export function openedWithControl(session: Row | null | undefined): boolean {
  return Boolean(
    session &&
      ['claude', 'codex'].includes(String(session['harness'])) &&
      session['first_prompt_control'] === true,
  );
}

/* The agent's published instruction when it carries `label`, or null. A correction the reader copied
   from Compass is never their words, so a copied instruction is not returned. */
export function sessionInstruction(session: Row | null | undefined, label: string): Row | null {
  const instruction = session?.['instruction'];
  if (!isRecord(instruction) || promptCopied(session, 'instruction')) return null;
  if (String(instruction['label'] || '') !== label) return null;
  return String(instruction['text'] == null ? '' : instruction['text']).trim() ? instruction : null;
}

export interface PromptCandidate {
  readonly text: string;
  readonly at: number | null;
  readonly source: string;
}

/* The prompt a source offers: the first prompt as published, or the latest one the harness states as
   work. Null where the harness publishes none or the words were a correction the reader copied. */
export function promptCandidate(
  session: Row | null | undefined,
  source: 'first-prompt' | 'latest-prompt',
): PromptCandidate | null {
  if (!session || !['claude', 'codex'].includes(String(session['harness']))) return null;
  let text = '';
  let at: number | null = null;
  if (source === 'first-prompt') {
    if (promptCopied(session, 'first_prompt')) return null;
    text = String(session['first_prompt'] || '');
    at = nextNumber(session['first_prompt_at']);
  } else if (session['harness'] === 'claude') {
    const asked = sessionInstruction(session, 'asked');
    if (asked) {
      text = String(asked['text'] || '');
      at = nextNumber(asked['at']);
    }
  } else if (session['prompt_states_work'] === true) {
    text = String(session['title'] || '');
    at = nextNumber(session['prompt_at']);
  }
  return text ? { text, at: at !== null && at > 0 ? at : null, source } : null;
}

export interface SessionGoalCandidate extends PromptCandidate {
  /** The condition is longer than the Goal field holds, so `text` is the server's excerpt of it. */
  readonly cut: boolean;
}

/* The goal a Claude Code or Codex session set with `/goal`, as the Goal field can hold it: the server's excerpt where
   the condition is longer than the field (`cut`), so the page, an adoption and the store agree on the words
   and none clips on its own. Null for another harness, no goal, or one with no moment, which an adoption
   refuses. */
export function sessionGoalCandidate(session: Row | null | undefined): SessionGoalCandidate | null {
  if (!session || !SESSION_GOAL_HARNESSES.includes(String(session['harness']))) return null;
  const stated = session['session_goal'];
  if (!isRecord(stated)) return null;
  const cut = stated['cut'] === true && typeof stated['offered'] === 'string';
  const words = cut ? stated['offered'] : stated['text'];
  const text = typeof words === 'string' ? words.trim() : '';
  const at = nextNumber(stated['at']);
  return text && at !== null && at > 0 ? { text, at, source: SESSION_GOAL, cut } : null;
}

export interface DraftOptions {
  /** The annotation store is on for this run: `annotate === true` in the payload. */
  readonly annotate: boolean;
  /** The server's sentence while the store cannot be read, or empty. Nothing is drafted over one. */
  readonly unreadable: string;
}

/* The goal a goal-less session arrives with: the first prompt as Compass publishes it, or the latest
   where no first prompt with a time is published, and null where neither can be adopted. Derived from the
   payload and never written. Nothing is drafted over a store this build cannot read, where saving could
   not save, and nothing over a session that opened with a harness control. */
export function intentDraft(
  session: Row,
  options: DraftOptions,
  chosen?: PromptCandidate | null,
): PromptCandidate | null {
  if (!options.annotate || options.unreadable) return null;
  if (chosen) return chosen;
  if (String(session['annotation_goal'] || '').trim()) return null;
  /* Ahead of the prompts, and ahead of the control check: a session that opened with `/goal` has no first
     prompt to draft, and its `/goal` is the goal it was given. */
  const stated = sessionGoalCandidate(session);
  if (stated) return stated;
  if (openedWithControl(session)) return null;
  for (const source of ['first-prompt', 'latest-prompt'] as const) {
    const candidate = promptCandidate(session, source);
    if (candidate && candidate.at !== null) return candidate;
  }
  return null;
}
