import { describe, expect, it, vi } from 'vitest';
import { LONG_JOB, EVIDENCE_PROGRESS } from '../../test/longProgress';
import { REGION_IDS } from '../shell/announcer';
import { byAction, driftBoard, mountDrift, press, textOf } from './testing';

const BLOCKED =
  'Compass could not confirm that the analysis process ended. It may still be running. No new result was saved. Recorded calls remain counted.';
const payload = (job: Record<string, unknown>) => ({ reading_jobs: { 'claude:s1': job } });
const blocked = { ...LONG_JOB, blocked_reason: 'cleanup-unresolved' };
const cue = () => document.getElementById(REGION_IDS.cue)?.textContent ?? '';

describe('long cleanup remains unconfirmed', () => {
  it('shows priority uncertainty on reload without announcements, requests or a promised result', async () => {
    const page = mountDrift({ payload: payload(blocked) });
    await page.settle();
    expect(textOf('[data-next-long-progress]')).toContain(BLOCKED);
    expect(textOf('[data-next-analyzing]')).not.toMatch(
      /Collecting source|result will appear|Analyzing drift/,
    );
    expect(textOf('[data-next-long-progress]')).toContain('Reserved call accounting is unknown.');
    expect(cue()).toBe('');
    expect(byAction('reading-cancel')).not.toBeNull();
    expect(page.allPosts()).toEqual([]);
    expect(page.gets('/api/reading-long-plan')).toBe(0);
  });
  it('announces a watched transition once and suppresses later normal stage announcements', async () => {
    const page = mountDrift({ payload: payload(LONG_JOB) });
    await page.settle();
    const say = vi.spyOn(page.shell.announcer, 'announce');
    await page.poll({ ...driftBoard({ payload: payload(blocked) }), generated: 1100 });
    expect(cue()).toBe(BLOCKED);
    await page.poll({
      ...driftBoard({ payload: payload({ ...blocked, progress: EVIDENCE_PROGRESS }) }),
      generated: 1200,
    });
    expect(cue()).toBe(BLOCKED);
    await page.go('#n=sessions');
    await page.go('#n=session:alpha%2Fapp:claude:s1');
    expect(say.mock.calls.filter((call) => call[1] === BLOCKED)).toHaveLength(1);
    expect(say.mock.calls.some((call) => call[1] === 'Reading long analysis evidence.')).toBe(
      false,
    );
    expect(textOf('[data-next-long-progress]')).not.toContain('Evidence pass 4 of 7');
    expect(page.allPosts()).toEqual([]);
  });
  it('keeps accepted Cancel and focus while blocked, with no fresh retry or second POST', async () => {
    const page = mountDrift({
      payload: payload(LONG_JOB),
      routes: { '/api/reading/cancel': () => 'hold' },
    });
    await page.settle();
    byAction('reading-cancel')?.focus();
    await press(byAction('reading-cancel'));
    await page.release(
      '/api/reading/cancel',
      new Response(JSON.stringify({ ok: true, cancelling: true }), { status: 202 }),
    );
    await page.poll({
      ...driftBoard({ payload: payload({ ...blocked, cancelling: true }) }),
      generated: 1200,
    });
    expect(textOf('[data-next-long-progress]')).toContain(BLOCKED);
    expect(document.activeElement).toBe(byAction('reading-cancel'));
    expect(byAction('reading-cancel')?.getAttribute('aria-disabled')).toBe('true');
    await press(byAction('reading-cancel'));
    expect(page.posts('/api/reading/cancel')).toBe(1);
    expect(document.body.textContent).not.toContain('The result will appear here.');
  });
  it('retains the warning if a Cancel answer arrives after the blocked poll', async () => {
    const page = mountDrift({
      payload: payload(LONG_JOB),
      routes: { '/api/reading/cancel': () => 'hold' },
    });
    await page.settle();
    await press(byAction('reading-cancel'));
    await page.poll({ ...driftBoard({ payload: payload(blocked) }), generated: 1100 });
    expect(textOf('[data-next-long-progress]')).toContain(BLOCKED);
    await page.release(
      '/api/reading/cancel',
      new Response(JSON.stringify({ ok: true, cancelling: true }), { status: 202 }),
    );
    expect(textOf('[data-next-long-progress]')).toContain(BLOCKED);
    expect(page.posts('/api/reading/cancel')).toBe(1);
  });
  it('prioritizes the closed token even if progress is unavailable, and newly drawn blocked jobs announce only the warning', async () => {
    const page = mountDrift({});
    await page.settle();
    await page.poll({
      ...driftBoard({ payload: payload({ ...blocked, progress: null }) }),
      generated: 1100,
    });
    expect(textOf('[data-next-long-progress]')).toBe(BLOCKED);
    expect(cue()).toBe(BLOCKED);
    expect(page.allPosts()).toEqual([]);
  });
  it('keeps an undrawn blocked transition silent when returning', async () => {
    const page = mountDrift({ payload: payload(LONG_JOB) });
    await page.settle();
    const say = vi.spyOn(page.shell.announcer, 'announce');
    await page.go('#n=sessions');
    await page.poll({ ...driftBoard({ payload: payload(blocked) }), generated: 1100 });
    await page.go('#n=session:alpha%2Fapp:claude:s1');
    expect(say.mock.calls.filter((call) => call[1] === BLOCKED)).toHaveLength(0);
    expect(textOf('[data-next-long-progress]')).toContain(BLOCKED);
  });
  it.each([
    { ...LONG_JOB, blocked_reason: '/raw/error' },
    { ...blocked, mode: 'ordinary' },
  ])('withholds unrecognized or ordinary metadata', async (job) => {
    const page = mountDrift({ payload: payload(job) });
    await page.settle();
    expect(document.body.textContent).not.toContain(BLOCKED);
    expect(document.body.textContent).not.toContain('/raw/error');
    expect(cue()).toBe('');
    expect(page.allPosts()).toEqual([]);
  });
});
