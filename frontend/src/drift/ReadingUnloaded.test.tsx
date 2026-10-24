import { screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { check, driftBoard, fact, json, mountDrift, press, textOf, openActivity } from './testing';

/* A press reads a session's messages back to its window start, which can be further than the board's own
   record reaches. A stored reading the reader merely opens loads no page, so one citing an entry the page
   does not hold says so and says where the reader's own request resolves it. The press the reader just saw
   finish reads the older pages itself. */

const path = '/api/session-record';
const ASSESSMENT = {
  revision_read: 1,
  revision_read_at: 90,
  window_start: 100,
  read_at: 1000,
  evidence_through: 1000,
  goal_source: 'typed',
  scope: 'last-turn',
  scope_text: 'Read up to its last turn.',
  stamp: 'model · m',
  cutoff: 'Evidence read to its end.',
  coverage: {
    tail_truncated: false,
    tail_start: null,
    unlisted: 0,
    unread_checks: 0,
    goal_source: 'typed',
  },
  criteria: {
    goal: {
      result: 'consistent with the evidence read',
      cites: ['early'],
      detail: '',
      clause: 'Keep the connection working',
    },
  },
};
/* A real row always publishes its activity, and the page reads the newest record page again only when it
   changes, so a poll that brings the same activity reads nothing. */
const session = {
  annotation_assessment: ASSESSMENT,
  annotation_window_start: 100,
  annotation_reading_count: 1,
  last_activity: 1000,
};
const FACTS = [check('c2', 600, 'passed')];
const recordBody = (extra: Record<string, unknown> = {}) => ({
  session: { harness: 'claude', sid: 's1' },
  entries: [fact('late', 900)],
  next: 'older',
  reached_start: false,
  bound: null,
  scanned_bytes: 1024,
  kinds: ['user_message', 'agent_message'],
  state: 'ok',
  ...extra,
});
const unloaded = () => document.querySelector('[data-next-unloaded]');

describe('a reading that cites an entry the page does not list', () => {
  it('says so, points at Show more, and stops saying it once the reader loads the entry', async () => {
    const page = mountDrift({
      session,
      facts: FACTS,
      routes: {
        [path]: (request) =>
          json(
            request.url.includes('before=')
              ? recordBody({
                  entries: [fact('early', 150, { type: 'agent_message', by: 'agent' })],
                  next: null,
                  reached_start: true,
                })
              : recordBody(),
          ),
      },
    });
    await page.settle();
    await openActivity();
    await page.settle();
    await openActivity();
    expect(unloaded()?.textContent).toBe(
      'This reading cites an entry that is not listed. Show more, under the list, may load it.',
    );
    // Nothing is loaded for the reader: the sentence leaves only once they ask.
    expect(page.gets(path)).toBe(1);
    await press(screen.getByRole('button', { name: 'Show 50 older entries' }));
    expect(page.gets(path)).toBe(2);
    expect(unloaded()).toBeNull();
    expect(textOf('[data-next-result-goal]')).not.toContain('Nothing resolvable was cited');
  });

  it('says nothing about loading when the record is already at its start', async () => {
    const page = mountDrift({
      session,
      facts: FACTS,
      routes: {
        [path]: () => json(recordBody({ entries: [], next: null, reached_start: true })),
      },
    });
    await page.settle();
    await openActivity();
    await page.settle();
    await openActivity();
    expect(unloaded()).toBeNull();
    expect(textOf('[data-next-result-goal]')).toContain('Nothing resolvable was cited');
  });

  it('counts several unloaded citations in one sentence', async () => {
    const many = {
      ...ASSESSMENT,
      criteria: { goal: { ...ASSESSMENT.criteria.goal, cites: ['early', 'earlier'] } },
    };
    const page = mountDrift({
      session: { ...session, annotation_assessment: many },
      facts: FACTS,
      routes: { [path]: () => json(recordBody()) },
    });
    await page.settle();
    await openActivity();
    await page.settle();
    await openActivity();
    expect(unloaded()?.textContent).toBe(
      'This reading cites 2 entries that are not listed. Show more, under the list, may load them.',
    );
  });
});

describe('the adopted-source note', () => {
  it('states the rule and does not claim this prompt reached it', async () => {
    const whole = {
      ...ASSESSMENT,
      goal_source: 'first-prompt',
      goal_source_at: 100,
      coverage: { ...ASSESSMENT.coverage, goal_source: 'whole' },
      criteria: { goal: { ...ASSESSMENT.criteria.goal, cites: ['c2'] } },
    };
    const page = mountDrift({
      session: { ...session, annotation_assessment: whole },
      facts: FACTS,
    });
    await page.settle();
    await openActivity();
    await page.settle();
    await openActivity();
    const text = document.body.textContent ?? '';
    expect(text).toContain(
      'The adopted source was found. Analyze reads at most the first 1,000 characters of any prompt.',
    );
    expect(text).not.toContain('Analyze read up to');
  });
});

describe('the adopted-source note over a /goal', () => {
  const stated = (goalSource: string) => ({
    ...session,
    annotation_assessment: {
      ...ASSESSMENT,
      goal_source: 'session-goal',
      goal_source_at: 100,
      coverage: { ...ASSESSMENT.coverage, goal_source: goalSource },
      criteria: { goal: { ...ASSESSMENT.criteria.goal, cites: ['c2'] } },
    },
  });
  const noteOf = async (goalSource: string) => {
    const page = mountDrift({ session: stated(goalSource), facts: FACTS });
    await page.settle();
    await openActivity();
    await page.settle();
    await openActivity();
    return document.body.textContent ?? '';
  };

  it('does not say a /goal that was not cut could not be read whole', async () => {
    const text = await noteOf('whole');
    expect(text).not.toContain('could not be read whole');
    expect(text).not.toContain('The adopted source was found');
  });

  it('still says so for a /goal the producer measured as cut', async () => {
    expect(await noteOf('excerpt')).toContain('The adopted source could not be read whole');
  });
});

/* The one read the page makes for the reader: the press they started has stored a reading that cites entries
   the board does not hold. Nothing else loads a page. */
describe('a finished press that cites an entry the page does not list', () => {
  const JOB = { id: 'j1', phase: 'read', steps: [{ phase: 'read', text: 'Reading it' }] };
  const running = { reading_jobs: { 'claude:s1': JOB } };
  const older = (request: { url: string }) =>
    json(
      request.url.includes('before=')
        ? recordBody({
            entries: [fact('early', 150, { type: 'agent_message', by: 'agent' })],
            next: null,
            reached_start: true,
          })
        : recordBody(),
    );
  const stored = { ...session, annotation_assessment: ASSESSMENT };
  const unstored = { annotation_window_start: 100 };

  it('reads older pages for the reader, until the citation resolves, and then says nothing is missing', async () => {
    const page = mountDrift({
      session: unstored,
      payload: running,
      facts: FACTS,
      routes: { [path]: older },
    });
    await page.settle();
    await openActivity();
    await page.settle();
    await openActivity();
    expect(page.gets(path)).toBe(1);
    await page.poll({ ...driftBoard({ session: stored }), generated: 1200 });
    await page.settle();
    await openActivity();
    await page.settle();
    await openActivity();
    expect(page.gets(path)).toBe(2);
    expect(unloaded()).toBeNull();
    expect(textOf('[data-next-result-goal]')).not.toContain('Nothing resolvable was cited');
  });

  it('reads nothing more when a poll alone brings the stored reading, since no press of this page ended', async () => {
    const page = mountDrift({
      session: unstored,
      facts: FACTS,
      routes: { [path]: older },
    });
    await page.settle();
    await openActivity();
    await page.settle();
    await openActivity();
    await page.poll({ ...driftBoard({ session: stored }), generated: 1200 });
    await page.settle();
    await openActivity();
    await page.settle();
    await openActivity();
    expect(page.gets(path)).toBe(1);
    expect(unloaded()).not.toBeNull();
  });

  it('reads nothing more when the press ended withheld, because it stored no reading', async () => {
    const page = mountDrift({
      session: stored,
      payload: running,
      facts: FACTS,
      routes: { [path]: older },
    });
    await page.settle();
    await openActivity();
    await page.settle();
    await openActivity();
    await page.poll({
      ...driftBoard({
        session: { ...stored, annotation_reading_withheld: 'The analysis was cancelled.' },
      }),
      generated: 1200,
    });
    await page.settle();
    await openActivity();
    await page.settle();
    await openActivity();
    expect(page.gets(path)).toBe(1);
  });
});
