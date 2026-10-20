import { describe, expect, it } from 'vitest';
import { datedClock } from '../observed/values';
import { byAction, fact, mountDrift, press, textOf } from './testing';
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
    await page.settle();
    expect(textOf('[data-next-reading-idle]')).toBe(
      `Read up to the last recorded entry at ${datedClock(900)}; the last turn was not recorded as finished.`,
    );
    expect(textOf('[data-next-result-heading]')).toContain('So far:');
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
  it('opens Why Analyze is off with the server’s sentence', async () => {
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
