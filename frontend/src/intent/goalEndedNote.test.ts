import { describe, expect, it } from 'vitest';
import { createAnnouncer } from '../shell/announcer';
import { createFakeClock } from '../transport/testing';
import { compatSessKey } from '../api/identity';
import {
  goalEndedNote,
  goalKey,
  goalUpdate,
  intentDrafted,
  noDraftWhy,
  type DraftInput,
} from './derive';
import { createHeld } from './held';

/* A cleared /goal over a session that opened with /goal is said once: in the "opened with /goal" sentence while
   that sentence is drawn, and in the note beside the Goal field when a chosen prompt hides the sentence. */

function cleared(chosen: boolean): DraftInput {
  const held = createHeld({ clock: createFakeClock(), announcer: createAnnouncer() });
  const session = {
    harness: 'claude',
    sid: 's1',
    first_prompt: '/goal a file exists',
    first_prompt_control: true,
    session_goal: null,
    session_goal_cleared: { at: 450 },
  };
  if (chosen)
    held.chosen.set(goalKey(session), {
      factId: 'd1',
      text: 'A direction',
      at: 910,
      cut: false,
      direction: true,
      linesAnswer: null,
    } as never);
  return {
    held,
    contexts: new Map(),
    payload: { annotate: true, annotate_cap: 240 },
    session,
    annotation: null,
  };
}

describe('an event on an earlier day', () => {
  it('names the day, as the Drift notes do, so it never reads as today', () => {
    const input = cleared(true);
    expect(goalEndedNote(input)).toMatch(
      /^Your \/goal was cleared at \d{4}-\d{2}-\d{2} \d\d:\d\d$/,
    );
    expect(noDraftWhy(cleared(false).session, null, input.payload)).toMatch(
      /cleared at \d{4}-\d{2}-\d{2} \d\d:\d\d\./,
    );
  });
});

describe('goalEndedNote over a cleared, control-opened session', () => {
  it('leaves the clear to the opened-with sentence while no draft hides it', () => {
    const input = cleared(false);
    expect(intentDrafted(input)).toBe(false);
    expect(noDraftWhy(input.session, input.annotation, input.payload)).toContain('was cleared at');
    expect(goalEndedNote(input)).toBe('');
  });

  it('says the clear beside the Goal field when a chosen prompt hides that sentence', () => {
    const input = cleared(true);
    expect(intentDrafted(input)).toBe(true);
    expect(goalEndedNote(input)).toMatch(
      /^Your \/goal was cleared at (\d{4}-\d{2}-\d{2} )?\d\d:\d\d$/,
    );
  });
});

/* The note is about the session's /goal. Over a Goal field that holds a draft it says only that, because the
   source line between the note and the box names the draft. */
function plain(prompt: Record<string, unknown>): DraftInput {
  const held = createHeld({ clock: createFakeClock(), announcer: createAnnouncer() });
  return {
    held,
    contexts: new Map(),
    payload: { annotate: true, annotate_cap: 240 },
    session: {
      harness: 'claude',
      sid: 's2',
      first_prompt: 'Ship the queue worker',
      first_prompt_at: 100,
      session_goal: null,
      session_goal_cleared: { at: 450 },
      ...prompt,
    },
    annotation: null,
  };
}

describe('goalEndedNote over a cleared /goal and a prompt draft', () => {
  it('leaves naming the draft to the source line under it', () => {
    const input = plain({});
    expect(goalEndedNote(input)).toMatch(
      /^Your \/goal was cleared at (\d{4}-\d{2}-\d{2} )?\d\d:\d\d$/,
    );
  });

  it('says nothing about a draft once the reader has typed their own words', () => {
    const input = plain({});
    input.held.goals.set(goalKey(input.session), 'My own words');
    expect(goalEndedNote(input)).toMatch(
      /^Your \/goal was cleared at (\d{4}-\d{2}-\d{2} )?\d\d:\d\d$/,
    );
  });

  it('says a Codex clear the same way', () => {
    const input = plain({ harness: 'codex' });
    expect(goalEndedNote(input)).toMatch(
      /^Your \/goal was cleared at (\d{4}-\d{2}-\d{2} )?\d\d:\d\d$/,
    );
  });

  it('says nothing about a draft where there is none', () => {
    const input = plain({ first_prompt: '', first_prompt_at: null });
    expect(goalEndedNote(input)).toMatch(
      /^Your \/goal was cleared at (\d{4}-\d{2}-\d{2} )?\d\d:\d\d$/,
    );
  });

  it('stays empty while the update offer is shown, and says the earlier end once it is not', () => {
    const offered = (savedAt: number): DraftInput => ({
      ...plain({
        session_goal: { text: 'A newer goal', at: 600, earlier: { how: 'replaced', at: 550 } },
      }),
      annotation: { goal: 'My own goal', goal_saved_at: savedAt, at: savedAt },
    });
    const input = offered(400);
    expect(goalUpdate(input)).not.toBeNull();
    expect(goalEndedNote(input)).toBe('');
    const settled = offered(700);
    expect(goalUpdate(settled)).toBeNull();
    expect(goalEndedNote(settled)).toMatch(/^Replaced an earlier \/goal at /);
  });

  it('says the same plain note over a goal found in the prompts, edited or not', () => {
    const input = plain({});
    const key = goalKey(input.session);
    input.held.found.set(compatSessKey(input.session), {
      text: 'Add a retry to the upload client',
      foundAt: 900,
      label: 'Detected from your prompts',
      cites: [],
    });
    input.held.goals.set(key, 'Add a retry to the upload client');
    expect(goalEndedNote(input)).toMatch(
      /^Your \/goal was cleared at (\d{4}-\d{2}-\d{2} )?\d\d:\d\d$/,
    );
    input.held.goals.set(key, 'Add a retry to the upload client, logged');
    expect(goalEndedNote(input)).toMatch(
      /^Your \/goal was cleared at (\d{4}-\d{2}-\d{2} )?\d\d:\d\d$/,
    );
  });
});
