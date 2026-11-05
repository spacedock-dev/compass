import { describe, expect, it, vi } from 'vitest';
import { LONG_DIAGNOSTIC, LONG_INCOMPLETE_SENTENCE, LATEST_OLDER } from '../../test/longDiagnostic';
import { EVIDENCE_PROGRESS, LONG_JOB } from '../../test/longProgress';
import { PARTIAL_READING, PARTIAL_WHY } from '../../test/longReading';
import { REGION_IDS } from '../shell/announcer';
import { check, fact, driftBoard, mountDrift, POLICY, readingPosts, textOf } from './testing';
import { LONG_WITHHELD } from './sentences';

const job = { ...LONG_JOB, started_at: 1001 };
const payload = (value: Record<string, unknown>) => ({ reading_jobs: { 'claude:s1': value } });
const cue = () => document.getElementById(REGION_IDS.cue)?.textContent ?? '';
const facts = [check('c1', 500, 'failed', { result_source: 'failed flag' })];
const session = {
  annotation_assessment: PARTIAL_READING,
  annotation_long_diagnostic: LONG_DIAGNOSTIC,
  annotation_reading_withheld: LONG_INCOMPLETE_SENTENCE,
  annotation_reading_withheld_at: 1100,
};

describe('the latest long outcome alongside a standing reading', () => {
  it('keeps a later ordinary failure ordinary when an older unbound long diagnostic remains', async () => {
    const failure = 'The reader did not produce a usable answer.';
    const page = mountDrift({
      facts,
      session: {
        annotation_assessment: PARTIAL_READING,
        annotation_long_diagnostic: { ...LONG_DIAGNOSTIC, outcome: 'interrupted', binding: null },
        annotation_reading_withheld: failure,
        annotation_reading_withheld_at: 1400,
      },
    });
    await page.settle();
    expect(textOf('[data-next-long-outcome]')).not.toContain(failure);
    expect(textOf('.next-cockpit-reading-outcome')).toContain(failure);
    expect(textOf('[data-next-long-outcome]')).toContain(
      'Compass stopped before this analysis outcome was saved.',
    );
  });

  for (const pending of [false, true]) {
    it(`keeps the latest incomplete outcome and minimum accounting visible${pending ? ' with pending direction and Pause' : ''}`, async () => {
      const page = mountDrift({
        session,
        facts: pending ? [...facts, fact('u2', 1050, { summary: 'Use a different queue' })] : facts,
        ...(pending ? { payload: { reading: { ...POLICY, off: true, consent: false } } } : {}),
      });
      await page.settle();
      const latest = textOf('[data-next-long-outcome]');
      expect(latest).toContain('Long analysis did not produce a new result.');
      expect(textOf('.next-cockpit-reading-outcome')).toContain(LONG_INCOMPLETE_SENTENCE);
      expect(latest).toContain('Calls reserved: at least 4.');
      expect(textOf('[data-next-result]')).toContain(LATEST_OLDER);
      expect(textOf('[data-next-result]')).toContain('The retry check failed.');
      expect(textOf('[data-next-result]')).toContain(PARTIAL_WHY);
      expect(document.querySelectorAll('[data-next-long-outcome]')).toHaveLength(1);
      expect(readingPosts(page)).toEqual([]);
    });
  }

  it('does not mark a newer reading, another revision, unbound or malformed metadata as older', async () => {
    const page = mountDrift({ session, facts });
    await page.settle();
    for (const changes of [
      { annotation_assessment: { ...PARTIAL_READING, read_at: 1200 } },
      {
        annotation_long_diagnostic: {
          ...LONG_DIAGNOSTIC,
          binding: { ...LONG_DIAGNOSTIC.binding, revision: 2 },
        },
      },
      { annotation_long_diagnostic: { ...LONG_DIAGNOSTIC, binding: null } },
      { annotation_long_diagnostic: { ...LONG_DIAGNOSTIC, complete: true } },
    ]) {
      await page.poll({ ...driftBoard({ session: { ...session, ...changes } }), generated: 1200 });
      expect(textOf('[data-next-result]')).not.toContain(LATEST_OLDER);
    }
    expect(document.querySelector('[data-next-long-outcome]')).toBeNull();
  });

  it('keeps qualified partial findings and unknown accounting without global reassurance', async () => {
    const page = mountDrift({
      facts,
      session: {
        annotation_assessment: { ...PARTIAL_READING, read_at: 1100 },
        annotation_long_diagnostic: {
          ...LONG_DIAGNOSTIC,
          outcome: 'partial',
          accounting: { state: 'unknown', totals: null, attempted_job: null },
        },
      },
    });
    await page.settle();
    expect(textOf('[data-next-long-outcome]')).toContain('Long analysis saved a partial result.');
    expect(textOf('[data-next-long-outcome]')).toContain('Reserved call accounting is unknown.');
    expect(textOf('[data-next-result]')).toContain(PARTIAL_WHY);
    expect(textOf('[data-next-result]')).not.toContain(LATEST_OLDER);
    expect(textOf('[data-next-long-outcome]')).not.toMatch(/complete coverage|all work|0 calls/i);
    expect(LONG_WITHHELD['long-incomplete']).toBe(LONG_INCOMPLETE_SENTENCE);
  });
});

describe('long job announcements', () => {
  it('announces a newly dated watched failure despite an older retained long diagnostic', async () => {
    const prior = {
      ...LONG_DIAGNOSTIC,
      outcome: 'interrupted',
      binding: { ...LONG_DIAGNOSTIC.binding, job_started_at: 500 },
    };
    const page = mountDrift({ session: { annotation_long_diagnostic: prior } });
    await page.settle();
    await page.poll({
      ...driftBoard({ payload: payload(job), session: { annotation_long_diagnostic: prior } }),
      generated: 1100,
    });
    await page.poll({
      ...driftBoard({
        session: {
          annotation_long_diagnostic: prior,
          annotation_reading_withheld: 'The reader did not produce a usable answer.',
          annotation_reading_withheld_at: 1200,
        },
      }),
      generated: 1300,
    });
    expect(cue()).toBe('The reader did not produce a usable answer.');
    await page.poll({
      ...driftBoard({ payload: payload({ ...job, id: 'later', started_at: 1400 }) }),
      generated: 1400,
    });
    await page.poll({
      ...driftBoard({
        session: {
          annotation_long_diagnostic: {
            ...prior,
            binding: { ...prior.binding, job_started_at: 1500 },
          },
          annotation_reading_withheld: 'A different newer job failed.',
          annotation_reading_withheld_at: 1600,
        },
      }),
      generated: 1700,
    });
    expect(cue()).toBe('');
  });

  it('announces watched stage transitions once, never each pass or repeated poll', async () => {
    const page = mountDrift({});
    await page.settle();
    const say = vi.spyOn(page.shell.announcer, 'announce');
    await page.poll({ ...driftBoard({ payload: payload(job) }), generated: 1100 });
    const evidence = { ...job, progress: EVIDENCE_PROGRESS };
    await page.poll({ ...driftBoard({ payload: payload(evidence) }), generated: 1200 });
    expect(cue()).toBe('Long analysis: reading evidence.');
    await page.poll({ ...driftBoard({ payload: payload(evidence) }), generated: 1300 });
    await page.poll({
      ...driftBoard({
        payload: payload({
          ...evidence,
          progress: { ...EVIDENCE_PROGRESS, evidence: { planned: 7, ended: 4, current: 5 } },
        }),
      }),
      generated: 1400,
    });
    expect(
      say.mock.calls.filter((call) => call[1] === 'Long analysis: reading evidence.'),
    ).toHaveLength(1);
    const final = {
      ...job,
      progress: {
        ...EVIDENCE_PROGRESS,
        stage: 'reconciliation',
        evidence: { planned: 7, ended: 7, current: null },
        reconciliation: { ordinal: 17, state: 'running' },
      },
    };
    await page.poll({ ...driftBoard({ payload: payload(final) }), generated: 1500 });
    expect(cue()).toBe('Long analysis: final comparison.');
    await page.poll({ ...driftBoard({ session }), generated: 1600 });
    expect(cue()).toBe(LONG_INCOMPLETE_SENTENCE);
    await page.poll({ ...driftBoard({ session }), generated: 1700 });
    expect(say.mock.calls.filter((call) => call[1] === LONG_INCOMPLETE_SENTENCE)).toHaveLength(1);
  });

  it('keeps reload and hidden changes silent and never calls an old assessment current success', async () => {
    const page = mountDrift({
      payload: payload(job),
      session: { annotation_assessment: PARTIAL_READING },
    });
    await page.settle();
    expect(cue()).toBe('');
    await page.poll({ ...driftBoard({ payload: payload(job) }), generated: 1100 });
    expect(cue()).toBe('');
    await page.go('#n=sessions');
    await page.poll({
      ...driftBoard({ payload: payload({ ...job, progress: EVIDENCE_PROGRESS }) }),
      generated: 1200,
    });
    expect(cue()).toBe('');
    await page.go('#n=session:alpha%2Fapp:claude:s1');
    await page.settle();
    expect(cue()).toBe('');
    await page.poll({
      ...driftBoard({
        session: {
          annotation_assessment: { ...PARTIAL_READING, stamp: 'unrelated edit' },
          annotation_long_diagnostic: { ...LONG_DIAGNOSTIC, outcome: 'completed', complete: null },
        },
      }),
      generated: 1300,
    });
    expect(cue()).not.toMatch(/finished|saved a result/i);
  });

  it('announces a bound new partial reading as partial and preserves specific cancellation', async () => {
    const page = mountDrift({});
    await page.settle();
    await page.poll({ ...driftBoard({ payload: payload(job) }), generated: 1100 });
    await page.poll({
      ...driftBoard({
        session: {
          annotation_assessment: { ...PARTIAL_READING, read_at: 1100 },
          annotation_long_diagnostic: { ...LONG_DIAGNOSTIC, outcome: 'partial' },
        },
      }),
      generated: 1200,
    });
    expect(cue()).toContain('Long analysis saved a partial result.');
    await page.poll({
      ...driftBoard({ payload: payload({ ...job, id: 'second', started_at: 1300 }) }),
      generated: 1300,
    });
    await page.poll({
      ...driftBoard({
        session: {
          annotation_reading_withheld: 'The analysis was cancelled.',
          annotation_reading_withheld_at: 1400,
          annotation_long_diagnostic: {
            ...LONG_DIAGNOSTIC,
            outcome: 'cancelled',
            binding: { ...LONG_DIAGNOSTIC.binding, job_started_at: 1300 },
          },
        },
      }),
      generated: 1400,
    });
    expect(cue()).toBe('The analysis was cancelled.');
  });
});
