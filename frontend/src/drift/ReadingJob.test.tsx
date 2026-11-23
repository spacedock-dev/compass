import { describe, expect, it } from 'vitest';
import { REGION_IDS } from '../shell/announcer';
import { byAction, driftBoard, json, mountDrift, press, textOf } from './testing';

const JOB = {
  id: 'j1',
  phase: 'read',
  steps: [
    { phase: 'collect', text: 'Collecting the record' },
    { phase: 'read', text: 'Reading it' },
    { phase: 'write', text: 'Writing the result' },
  ],
};

const withJob = (job: Record<string, unknown> | null) => ({
  reading_jobs: job ? { 'claude:s1': job } : {},
});
const cue = () => document.getElementById(REGION_IDS.cue)?.textContent ?? '';
const cancels = (page: {
  state: { requests: { method: string; path: string; body: unknown }[] };
}) => page.state.requests.filter((r) => r.method === 'POST' && r.path === '/api/reading/cancel');

describe('a running analysis', () => {
  it('draws each step by where the published phase sits, with no role and no check mark', async () => {
    const page = mountDrift({ payload: withJob(JOB), session: { state: 'working' } });
    await page.settle();
    await page.settle();
    const steps = [...document.querySelectorAll('.next-cockpit-reading-step')];
    expect(steps.map((step) => step.getAttribute('data-state'))).toEqual([
      'done',
      'active',
      'todo',
    ]);
    expect(steps[1]?.getAttribute('aria-current')).toBe('step');
    const box = document.querySelector('.next-cockpit-reading-job') as HTMLElement;
    expect(box.getAttribute('role')).toBeNull();
    expect(textOf('.next-cockpit-reading-job-title')).toBe('Checking progress');
    expect(textOf('.next-cockpit-reading-job-note')).toContain('Reads only the work so far');
    // No new press is offered while one runs.
    expect(byAction('reading-ask')).toBeNull();
  });

  it('marks every step still to come under a phase it does not know', async () => {
    const page = mountDrift({ payload: withJob({ ...JOB, phase: 'novel' }) });
    await page.settle();
    await page.settle();
    expect(
      [...document.querySelectorAll('.next-cockpit-reading-step')].map((step) =>
        step.getAttribute('data-state'),
      ),
    ).toEqual(['todo', 'todo', 'todo']);
  });
});

describe('Cancel', () => {
  it('names the exact job, sends one request however it is pressed, and takes the board at its word', async () => {
    const page = mountDrift({
      payload: withJob(JOB),
      routes: { '/api/reading/cancel': () => 'hold' },
    });
    await page.settle();
    await page.settle();
    const cancel = byAction('reading-cancel') as HTMLElement;
    await press(cancel);
    await press(byAction('reading-cancel'));
    await press(byAction('reading-cancel'));
    expect(cancels(page)).toHaveLength(1);
    expect(cancels(page)[0]?.body).toMatchObject({
      harness: 'claude',
      sid: 's1',
      job: 'j1',
      press: true,
      observer_model: 1,
    });
    page.state.data = driftBoard({ payload: withJob({ ...JOB, cancelling: true }) });
    await page.release('/api/reading/cancel', json({ ok: true, cancelling: true }, 202));
    await page.settle();
    expect(byAction('reading-cancel')?.getAttribute('aria-disabled')).toBe('true');
    expect(cancels(page)).toHaveLength(1);
  });

  it('keeps the cancelling flag the server published across a reload', async () => {
    const page = mountDrift({ payload: withJob({ ...JOB, cancelling: true }) });
    await page.settle();
    await page.settle();
    expect(byAction('reading-cancel')?.getAttribute('aria-disabled')).toBe('true');
    await press(byAction('reading-cancel'));
    expect(cancels(page)).toHaveLength(0);
  });

  it('says it could not confirm a lost answer, never retries, and never shows it under a newer job', async () => {
    const page = mountDrift({
      payload: withJob(JOB),
      routes: { '/api/reading/cancel': () => new Response('x', { status: 500 }) },
    });
    await page.settle();
    await page.settle();
    await press(byAction('reading-cancel'));
    await page.settle();
    expect(textOf('.next-cockpit-reading-job')).toContain('Could not confirm the cancel');
    await page.advance(60_000);
    expect(cancels(page)).toHaveLength(1);
    // Another job: the old failure is about the old job.
    await page.poll({ ...driftBoard({ payload: withJob({ ...JOB, id: 'j2' }) }), generated: 1200 });
    expect(textOf('.next-cockpit-reading-job')).not.toContain('Could not confirm the cancel');
  });

  it('treats a not-running answer as the board telling it the job ended', async () => {
    const page = mountDrift({
      payload: withJob(JOB),
      routes: {
        '/api/reading/cancel': () => json({ ok: false, reason: 'not-running' }, 409),
      },
    });
    await page.settle();
    await page.settle();
    page.state.data = driftBoard();
    await press(byAction('reading-cancel'));
    await page.settle();
    expect(document.querySelector('[data-next-analyzing]')).toBeNull();
    expect(textOf('.next-cockpit-reading-job')).toBe('');
  });
});

describe('the announcements a running analysis makes', () => {
  it('says nothing for a job already running when the page loaded, and one outcome when it ends', async () => {
    const page = mountDrift({ payload: withJob(JOB) });
    await page.settle();
    await page.settle();
    expect(cue()).toBe('');
    // Redraws and a phase revision say nothing again.
    await page.poll({
      ...driftBoard({ payload: withJob({ ...JOB, phase: 'write' }) }),
      generated: 1100,
    });
    expect(cue()).toBe('');
    const stored = {
      revision_read: 3,
      read_at: 1500,
      criteria: {},
    };
    await page.poll({
      ...driftBoard({ session: { annotation_assessment: stored } }),
      generated: 1200,
    });
    expect(cue()).toBe('The progress check finished. Its result is in Is it on track?');
  });

  it("announces a job it saw begin, once, and a withheld end in the server's words", async () => {
    const page = mountDrift({});
    await page.settle();
    await page.settle();
    await page.poll({ ...driftBoard({ payload: withJob(JOB) }), generated: 1100 });
    expect(cue()).toBe('Checking progress');
    await page.poll({
      ...driftBoard({ payload: withJob({ ...JOB, phase: 'write' }) }),
      generated: 1150,
    });
    expect(cue()).toBe('Checking progress');
    await page.poll({
      ...driftBoard({ session: { annotation_reading_withheld: 'The analysis was cancelled.' } }),
      generated: 1200,
    });
    expect(cue()).toBe('The analysis was cancelled.');
  });

  it('never announces a job that began while no card was drawn', async () => {
    const page = mountDrift({});
    await page.settle();
    await page.settle();
    await page.go('#n=sessions');
    await page.poll({ ...driftBoard({ payload: withJob(JOB) }), generated: 1100 });
    await page.go('#n=session:alpha%2Fapp:claude:s1');
    await page.settle();
    expect(cue()).toBe('');
  });

  it('never announces the end of a job whose box it did not draw', async () => {
    const page = mountDrift({});
    await page.settle();
    await page.settle();
    await page.go('#n=sessions');
    await page.poll({ ...driftBoard({ payload: withJob(JOB) }), generated: 1100 });
    await page.poll({
      ...driftBoard({ session: { annotation_reading_withheld: 'The analysis was cancelled.' } }),
      generated: 1200,
    });
    await page.go('#n=session:alpha%2Fapp:claude:s1');
    await page.settle();
    expect(cue()).toBe('');
  });
});
