import { openSessionTechnicalTab } from '../../test/sessionTechnical';
import { act, fireEvent, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { check, mountDrift } from '../drift/testing';
import { control, editGoal, goalBox, lineBoxes, mountSession, text, type } from './panel.testing';

const settle = async (page: { settle: () => Promise<void> }) => {
  await page.settle();
  await page.settle();
};

const outcomes = () =>
  document.querySelector<HTMLElement>('.next-cockpit-held-lines [data-slot="accordion-trigger"]');

describe('the first view of a session', () => {
  it('folds the expected outcome into a closed accordion, and keeps Add a line inside it', async () => {
    const page = mountSession();
    await settle(page);
    expect(outcomes()?.getAttribute('aria-expanded')).toBe('false');
    expect(document.querySelector('[data-next-cockpit-held-field="goal"]')).not.toBeNull();
    const add = control('held-line-add');
    expect(add?.closest('[data-slot="accordion-content"]')).not.toBeNull();
    expect(add?.closest('.next-cockpit-held-footer')).toBeNull();
    await act(async () => {
      fireEvent.click(outcomes() as HTMLElement);
    });
    await page.settle();
    expect(outcomes()?.getAttribute('aria-expanded')).toBe('true');
  });

  it('opens by itself when a departure on show cites an outcome line nothing saves now', async () => {
    const page = mountDrift({
      store: { lines: [] },
      session: {
        annotation_assessment: {
          revision_read: 3,
          revision_read_at: 990,
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
              cites: [],
              detail: '',
              clause: 'Ship',
            },
            line_1: {
              result: 'departure',
              cites: ['c1'],
              detail: 'It stopped running the tests.',
              clause: 'Tests pass',
            },
          },
        },
        annotation_window_start: 100,
        annotation_reading_count: 1,
      },
      facts: [check('c1', 500, 'failed', { result_source: 'failed flag', summary: 'pytest -q' })],
    });
    await settle(page);
    editGoal();
    expect(outcomes()?.getAttribute('aria-expanded')).toBe('true');
  });

  it('opens by itself over saved outcome lines, and a reader who closes it keeps it closed', async () => {
    const page = mountSession({ session: { annotation_line_1: 'A passing check' } });
    await settle(page);
    expect(outcomes()?.getAttribute('aria-expanded')).toBe('true');
    await act(async () => {
      fireEvent.click(outcomes() as HTMLElement);
    });
    await page.settle();
    expect(outcomes()?.getAttribute('aria-expanded')).toBe('false');
  });

  it('offers one optional outcome field and draws its tools from the first view', async () => {
    const page = mountSession();
    await settle(page);
    expect(lineBoxes()).toHaveLength(1);
    expect(text('.next-cockpit-held-lines [data-slot="accordion-trigger"]')).toBe(
      'What “done” looks like (optional) · up to 6 lines',
    );
    // Drawn before the reader types, as the design has them.
    expect(control('held-line-add')).not.toBeNull();
    expect(control('held-line-remove')).not.toBeNull();
    type(lineBoxes()[0] as HTMLTextAreaElement, 'A passing check');
    expect(control('held-line-add')).not.toBeNull();
    expect(control('held-line-remove')).not.toBeNull();
    // An outcome edit is something Undo changes undoes, so it wakes.
    expect(control('held-undo')?.getAttribute('aria-disabled')).not.toBe('true');
  });

  it('keeps Save visible, Clear in the editor and the monitor in technical details', async () => {
    const page = mountSession();
    await settle(page);
    expect(control('held-save')).not.toBeNull();
    expect(control('held-undo')?.getAttribute('aria-disabled')).toBe('true');
    expect(document.querySelector('[data-next-session-more]')).toBeNull();
    const intent = document.querySelector('[aria-labelledby="next-session-intent-heading"]');
    expect(control('held-clear')).not.toBeNull();
    expect(intent?.querySelector('.next-session-drift-head')).toBeNull();
    expect(control('live-monitor')).toBeNull();
    await openSessionTechnicalTab('AI use and privacy');
    expect(control('live-monitor')).toBeVisible();
    expect(text('.next-session-reentry-none')).toBe('');
    type(goalBox(), 'Changed goal');
    expect(control('held-undo')).not.toBeNull();
    await act(async () => {
      fireEvent.click(control('held-undo') as Element);
    });
    expect(control('held-undo')?.getAttribute('aria-disabled')).toBe('true');
  });

  it('explains shortened prompt provenance in saved Goal read mode', async () => {
    const page = mountDrift({
      store: {
        goal: 'Ship the queue…',
        goal_source: 'first-prompt',
        goal_source_at: 100,
      },
    });
    await settle(page);
    expect(text('[data-next-cockpit-goal-source]')).toContain(
      'Shown as an excerpt. A progress check can read up to the first 1,000 characters of the original prompt',
    );
    expect(screen.getByRole('button', { name: 'Edit goal' })).toBeVisible();
  });

  it('warns beside the goal before typing on an ended session', async () => {
    const page = mountSession({ session: { ended_at: 999 } });
    await settle(page);
    fireEvent.click(screen.getByRole('button', { name: 'How goals work' }));
    expect(text('[data-next-ended-goal]')).toContain(
      'This session has ended. Compass keeps goals you save now for reference. A progress check uses the goal you saved before the session ended or a goal taken from one of your prompts.',
    );
    expect(goalBox().value).toBe('Ship the queue worker');
  });

  it('keeps a typed goal saved before the end eligible without contradicting Analyze', async () => {
    const page = mountDrift({
      store: { goal: 'Ship the queue worker' },
      session: {
        ended_at: 900,
        annotation_goal_saved_at: 700,
        reading_eligibility: { ok: true },
      },
    });
    await settle(page);
    expect(screen.getByText('Ship the queue worker')).toBeVisible();
    fireEvent.click(screen.getByRole('button', { name: 'How goals work' }));
    expect(control('reading-ask')).not.toBeNull();
    expect(control('reading-ask')?.getAttribute('aria-disabled')).not.toBe('true');
    expect(text('[data-next-ended-goal]')).toContain(
      'A progress check uses the goal you saved before the session ended',
    );
    expect(text('[data-next-ended-goal]')).not.toContain('can only read');
  });

  it('keeps Activity log open and held fields across refresh and a remount', async () => {
    const page = mountSession({ store: { goal: 'Saved', lines: ['A check'], revision: 1 } });
    await settle(page);
    const trigger = () =>
      document.querySelector('[data-next-session-full-activity] .technical-details-trigger');
    expect(trigger()?.getAttribute('aria-expanded')).toBe('false');
    await act(async () => {
      fireEvent.click(trigger() as Element);
    });
    editGoal();
    type(goalBox(), 'Held words');
    type(lineBoxes()[0] as HTMLTextAreaElement, 'Held outcome');
    await page.poll({ ...(page.state.data as object), generated: 1100 });
    expect(trigger()?.getAttribute('aria-expanded')).toBe('true');
    await page.go('#n=sessions');
    await page.go('#n=session:alpha%2Fapp:claude:s1');
    expect(trigger()?.getAttribute('aria-expanded')).toBe('true');
    expect(goalBox().value).toBe('Held words');
    expect(lineBoxes()[0]?.value).toBe('Held outcome');
    expect(page.posts()).toBe(0);
  });
});
