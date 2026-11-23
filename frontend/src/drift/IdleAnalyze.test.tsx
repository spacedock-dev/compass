import { openSessionTechnicalTab } from '../../test/sessionTechnical';
import { describe, expect, it } from 'vitest';
import { screen } from '@testing-library/react';
import { datedClock } from '../observed/values';
import { byAction, fact, mountDrift, press, textOf, POLICY } from './testing';
import { SCOPE_TEXT_IDLE, WHY_OFF } from './sentences';

/* Owner, 2026-10-20: an idle Claude Code session whose last turn has no recorded finish is analyzed up to its
   last recorded entry and says so, and a press on a refused Analyze shows why it is off. */

const IDLE_READING = {
  revision_read: 3,
  revision_read_at: 990,
  window_start: 100,
  read_at: 1000,
  evidence_through: 900,
  goal_source: 'typed',
  scope: 'mid-flight',
  scope_text: SCOPE_TEXT_IDLE,
  criteria: {
    goal: { result: 'departure', cites: ['m1'], detail: 'It stopped.', clause: 'Ship the queue' },
  },
};
const SAID = [fact('m1', 600, { type: 'agent_message', by: 'agent' })];

describe('an idle session analyzed up to its last recorded entry', () => {
  it('says where it read to, in the reader’s clock, and never reads as a final verdict', async () => {
    const page = mountDrift({
      session: {
        state: 'idle',
        turn_end_at: null,
        annotation_assessment: IDLE_READING,
        annotation_window_start: 100,
      },
      facts: SAID,
    });
    await page.settle();
    await openSessionTechnicalTab('Evidence');
    await page.settle();
    expect(textOf('[data-next-reading-idle]')).toBe(
      `Read up to the last recorded entry at ${datedClock(900)}; the last turn was not recorded as finished.`,
    );
    expect(textOf('[data-next-drift-verdict]')).toContain('So far:');
  });

  it('draws no idle line for a reading of a running session', async () => {
    const page = mountDrift({
      session: {
        annotation_assessment: { ...IDLE_READING, scope_text: undefined },
        annotation_window_start: 100,
      },
      facts: SAID,
    });
    await page.settle();
    await page.settle();
    expect(document.querySelector('[data-next-reading-idle]')).toBeNull();
  });
});

describe('a press on a refused Analyze', () => {
  it.each([
    ['settling', 'Ready in a few seconds.', 'The session ended. {control} opens by itself.'],
    ['stop-settling', 'Ready in a few seconds.', 'The turn ended. {control} opens by itself.'],
    [
      'idle-unknown',
      '{control} opens while this session runs or once it ends.',
      '{control} opens while the session works, or once its end is observed.',
    ],
    [
      'unobservable',
      'This harness sends no events, so {control} opens only while it runs.',
      'A reading can run only while the session is working.',
    ],
    [
      'turn-stop',
      '{control} opens while a turn runs or once the session ends.',
      'Compass reads this harness only while a turn runs or after its session ends.',
    ],
  ] as const)(
    'keeps the first and repeat controls beside the %s explanation',
    async (reason, short, detail) => {
      for (const hasReading of [false, true]) {
        const label = hasReading ? 'Check progress again' : 'Check progress';
        const sentence = detail.replace('{control}', label);
        const page = mountDrift({
          session: {
            acquisition: 'event',
            annotation_assessment: hasReading ? IDLE_READING : null,
            reading_eligibility: { ok: false, reason, until: null, sentence },
          },
          facts: SAID,
        });
        await page.settle();
        const control = screen.getByRole('button', { name: label });
        expect(control).toBeVisible();
        expect(control.getAttribute('aria-disabled')).toBe('true');
        expect(textOf('#next-cockpit-reading-refused')).toBe(short.replace('{control}', label));
        const why = screen.getByRole('button', { name: 'Why the progress check is off' });
        await press(control);
        await page.settle();
        expect(why.getAttribute('aria-expanded')).toBe('true');
        expect(screen.getByText(sentence)).toBeVisible();
        page.unmount();
      }
    },
  );

  it('opens Why the progress check is off with the server’s sentence', async () => {
    const sentence =
      'You saved these words after this session ended, so there is no work after them.';
    const page = mountDrift({
      session: {
        reading_eligibility: { ok: false, reason: 'revision-after-end', until: null, sentence },
      },
    });
    await page.settle();
    await page.settle();
    const why = [...document.querySelectorAll('.ctl-disclosure')].find((node) =>
      node.textContent?.includes(WHY_OFF),
    ) as HTMLElement;
    expect(why).toBeDefined();
    expect(why.hasAttribute('data-open')).toBe(false);
    await press(byAction('reading-ask') as HTMLElement);
    await page.settle();
    expect(why.hasAttribute('data-open')).toBe(true);
    expect(why.textContent).toContain(sentence);
    expect(document.body.textContent).not.toContain("Why it can't read");
  });
});

it('updates the cost from the measured daily count after a check', async () => {
  const policy = { ...POLICY, used: 89, limit: 100 };
  const page = mountDrift({ payload: { reading: policy } });
  await page.settle();
  const cost = () => textOf('[data-next-check-cost]');
  expect(cost()).toBe('Uses AI');
  await press(screen.getByRole('button', { name: 'Check progress' }));
  expect(page.posts('/api/reading')).toBe(1);
  await page.poll({ ...(page.state.data as object), reading: { ...policy, used: 90 } });
  expect(cost()).toBe('Uses AI · 10 of 100 daily checks left');
  await page.poll({ ...(page.state.data as object), reading: { ...policy, used: 100 } });
  expect(cost()).toBe('Uses AI · 0 of 100 daily checks left');
  await page.poll({
    ...(page.state.data as object),
    reading: { ...policy, reason: 'store-unavailable' },
  });
  expect(cost()).toBe('Uses AI');
});
