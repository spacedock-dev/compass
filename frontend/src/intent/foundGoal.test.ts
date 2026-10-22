import { describe, expect, it } from 'vitest';
import { createAnnouncer } from '../shell/announcer';
import { createFakeClock } from '../transport/testing';
import {
  foundGoal,
  goalKey,
  intentChanges,
  intentDraft,
  intentUnsaved,
  type DraftInput,
} from './derive';
import { createHeld, type FoundGoal } from './held';

/* The working goal, in the order the owner ruled: the reader's saved goal, then a /goal, then a goal found in the
   prompts, then today's drafts from the first or latest prompt. A found goal stands only while the box still
   holds exactly its words, so editing replaces it, and nothing outranked by another source is ever drawn. */

const FOUND: FoundGoal = {
  text: 'The upload client retries a dropped connection and resumes',
  foundAt: 1_760_000_500,
  label: 'Claude Code',
  cites: [{ factId: 'f1', ordinal: 1, at: 100, quotes: ['add a retry'] }],
};

function input(
  options: {
    readonly session?: Record<string, unknown>;
    readonly annotation?: Record<string, unknown> | null;
    readonly box?: string | null;
    readonly found?: FoundGoal | null;
    readonly annotate?: boolean;
  } = {},
): DraftInput {
  const held = createHeld({ clock: createFakeClock(), announcer: createAnnouncer() });
  const session = {
    harness: 'claude',
    sid: 's1',
    first_prompt: 'Ship the queue worker',
    first_prompt_at: 100,
    ...(options.session ?? {}),
  };
  const key = goalKey(session);
  const found = options.found === undefined ? FOUND : options.found;
  if (found) held.found.set('claude:s1', found);
  const box = options.box === undefined ? FOUND.text : options.box;
  if (box !== null) held.goals.set(key, box);
  return {
    held,
    contexts: new Map(),
    payload: { annotate: options.annotate ?? true, annotate_cap: 240 },
    session,
    annotation: (options.annotation as DraftInput['annotation']) ?? null,
  };
}

describe('a found goal', () => {
  it('stands while the box holds its words and nothing outranks it', () => {
    expect(foundGoal(input())).toEqual(FOUND);
  });

  it('is replaced by an edit, and stands again only if the reader types the same words back', () => {
    expect(foundGoal(input({ box: `${FOUND.text}, and a test` }))).toBeNull();
    expect(foundGoal(input({ box: null }))).toBeNull();
    expect(foundGoal(input({ box: FOUND.text }))).toEqual(FOUND);
  });

  it('never stands over a goal the reader saved', () => {
    expect(foundGoal(input({ annotation: { goal: 'My own goal', revision: 2 } }))).toBeNull();
  });

  it('never stands over a /goal the session set, and the /goal is the draft', () => {
    const session = { session_goal: { text: 'The findings file exists', at: 500 } };
    const page = input({ session });
    expect(foundGoal(page)).toBeNull();
    expect(intentDraft(page)?.text).toBe('The findings file exists');
  });

  it('stands only where annotations are on', () => {
    expect(foundGoal(input({ annotate: false }))).toBeNull();
  });

  it('is nothing where none was found', () => {
    expect(foundGoal(input({ found: null }))).toBeNull();
  });

  it('leaves the prompt drafts as the box would draw them with no found goal', () => {
    const page = input({ box: null, found: null });
    expect(intentDraft(page)?.text).toBe('Ship the queue worker');
    expect(intentDraft(page)?.source).toBe('first-prompt');
  });
});

describe('a found goal as the working goal', () => {
  it('is not an unsaved edit, so Analyze drift is not refused over it, and Undo has nothing to undo', () => {
    const page = input();
    expect(intentUnsaved(page)).toBe(false);
    expect(intentChanges(page).undoable).toBe(false);
    // Save intent still stores it as the reader's typed words.
    expect(intentChanges(page).goal).toBe(true);
  });

  it('is an edit again once the reader changes the words', () => {
    const page = input({ box: `${FOUND.text}, and a test` });
    expect(intentUnsaved(page)).toBe(true);
    expect(intentChanges(page).undoable).toBe(true);
  });
});
