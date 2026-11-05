import { describe, expect, it } from 'vitest';
import { EVIDENCE_PROGRESS, LONG_JOB } from '../../test/longProgress';
import { byAction, driftBoard, mountDrift, press, textOf } from './testing';

const payload = (job: Record<string, unknown>) => ({ reading_jobs: { 'claude:s1': job } });
const progressText = () => textOf('[data-next-long-progress]');

describe('a person watching a long analysis', () => {
  it('sees unknown source and accounting on mount and redraw without sending any action', async () => {
    const page = mountDrift({ payload: payload(LONG_JOB) });
    await page.settle();
    expect(progressText()).toContain('Collecting source');
    expect(progressText()).toContain('Source files verified: unknown.');
    expect(progressText()).toContain('Evidence pass count: unknown.');
    expect(progressText()).toContain('Reserved call accounting is unknown.');
    expect(progressText()).not.toMatch(/0 of 0|%|calls reserved: 0/i);
    await page.poll({ ...driftBoard({ payload: payload(LONG_JOB) }), generated: 1100 });
    await page.go('#n=sessions');
    await page.go('#n=session:alpha%2Fapp:claude:s1');
    await page.settle();
    expect(progressText()).toContain('Reserved call accounting is unknown.');
    expect(page.state.requests.filter((request) => request.method === 'POST')).toEqual([]);
    expect(
      page.state.requests.filter((request) => request.path.startsWith('/api/reading-long-plan')),
    ).toEqual([]);
    expect(document.querySelector('[data-next-long-progress]')?.getAttribute('role')).toBeNull();
  });

  it('shows the actual fourth pass of seven and preserves one explicit Cancel across polls', async () => {
    const job = { ...LONG_JOB, phase: 'read', progress: EVIDENCE_PROGRESS };
    const page = mountDrift({
      payload: payload(job),
      routes: { '/api/reading/cancel': () => 'hold' },
    });
    await page.settle();
    expect(progressText()).toContain('Evidence pass 4 of 7');
    expect(progressText()).toContain('Evidence passes finished: 3 of 7.');
    expect(progressText()).toContain('Calls reserved: 4.');
    expect(progressText()).toContain('Assembled input reserved: 24,000 bytes.');
    expect(progressText()).toContain('Reply space reserved: 32,768 bytes.');
    expect(progressText()).not.toMatch(/of 16|of 17|successful|tokens|%/i);
    const cancel = byAction('reading-cancel');
    cancel?.focus();
    await page.poll({ ...driftBoard({ payload: payload(job) }), generated: 1100 });
    expect(document.activeElement).toBe(byAction('reading-cancel'));
    await press(byAction('reading-cancel'));
    await press(byAction('reading-cancel'));
    const requests = page.state.requests.filter((request) => request.method === 'POST');
    expect(requests).toHaveLength(1);
    expect(requests[0]?.path).toBe('/api/reading/cancel');
    expect(requests[0]?.body).toMatchObject({ job: 'long-j1', press: true });
  });

  it('names the final comparison without calling reserved slot 17 the seventeenth actual pass', async () => {
    const progress = {
      ...EVIDENCE_PROGRESS,
      stage: 'reconciliation',
      evidence: { planned: 7, ended: 7, current: null },
      reconciliation: { ordinal: 17, state: 'running' },
      accounting: { ...EVIDENCE_PROGRESS.accounting, state: 'minimum' },
    };
    const page = mountDrift({ payload: payload({ ...LONG_JOB, progress }) });
    await page.settle();
    expect(progressText()).toContain('Final comparison');
    expect(progressText()).toContain('Evidence passes finished: 7 of 7.');
    expect(progressText()).toContain('Calls reserved: at least 4.');
    expect(progressText()).toContain('Assembled input reserved: at least 24,000 bytes.');
    expect(progressText()).not.toMatch(/pass 17|of 8|complete|successful/i);
    await page.poll({
      ...driftBoard({
        payload: payload({
          ...LONG_JOB,
          progress: {
            ...progress,
            stage: 'publication',
            reconciliation: { ordinal: 17, state: 'ended' },
          },
        }),
      }),
      generated: 1100,
    });
    expect(progressText()).toContain('Saving outcome');
  });

  it('withholds malformed progress while retaining the real Cancel control', async () => {
    const page = mountDrift({
      payload: payload({
        ...LONG_JOB,
        progress: { ...EVIDENCE_PROGRESS, evidence: { planned: 7, ended: 3, current: 17 } },
      }),
    });
    await page.settle();
    expect(progressText()).toBe('Long analysis progress is unavailable.');
    expect(byAction('reading-cancel')).not.toBeNull();
    expect(page.state.requests.filter((request) => request.method === 'POST')).toEqual([]);
  });
});
