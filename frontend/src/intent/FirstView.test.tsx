import { act, fireEvent, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { mountDrift } from '../drift/testing';
import { control, goalBox, lineBoxes, mountSession, text, type } from './panel.testing';

const settle = async (page: { settle: () => Promise<void> }) => {
  await page.settle();
  await page.settle();
};

describe('the first view of a session', () => {
  it('offers one optional outcome field and draws its tools from the first view', async () => {
    const page = mountSession();
    await settle(page);
    expect(lineBoxes()).toHaveLength(1);
    expect(text('.next-cockpit-held-lines label')).toBe('Expected outcome · up to 6 lines');
    // Drawn before the reader types, as the design has them.
    expect(control('held-line-add')).not.toBeNull();
    expect(control('held-line-remove')).not.toBeNull();
    type(lineBoxes()[0] as HTMLTextAreaElement, 'A passing check');
    expect(control('held-line-add')).not.toBeNull();
    expect(control('held-line-remove')).not.toBeNull();
    // An outcome edit is something Undo changes undoes, so it wakes.
    expect(control('held-undo')?.getAttribute('aria-disabled')).not.toBe('true');
  });

  it('keeps Save visible, Clear in the Intent card menu and the monitor behind Drift settings in the Drift card head', async () => {
    const page = mountSession();
    await settle(page);
    expect(control('held-save')).not.toBeNull();
    expect(control('held-undo')?.getAttribute('aria-disabled')).toBe('true');
    expect(document.querySelector('[data-next-session-more]')).toBeNull();
    const intent = document.querySelector('[aria-labelledby="next-session-intent-heading"]');
    // Clear is in the card's quiet menu, which holds it once the reader opens it.
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'More about these words' }));
    });
    await page.settle();
    expect(control('held-clear')).not.toBeNull();
    expect(intent?.querySelector('.next-session-drift-head')).toBeNull();
    // The switch is inside the settings the head offers, which open over the page, so it is not a node of the head.
    expect(document.querySelector('.next-session-drift-head')?.textContent).toContain(
      'Drift settings',
    );
    expect(control('live-monitor')).not.toBeNull();
    expect(text('.next-session-reentry-none')).toBe('');
    type(goalBox(), 'Changed goal');
    expect(control('held-undo')).not.toBeNull();
    await act(async () => {
      fireEvent.click(control('held-undo') as Element);
    });
    expect(control('held-undo')?.getAttribute('aria-disabled')).toBe('true');
  });

  it('warns beside the goal before typing on an ended session', async () => {
    const page = mountSession({ session: { ended_at: 999 } });
    await settle(page);
    expect(text('[data-next-cockpit-held-field="goal"]')).toContain(
      'This session has ended. Words you save now cannot be read against it; your saved intent and the goal drafted from your prompt still can.',
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
    expect(goalBox().value).toBe('Ship the queue worker');
    expect(control('reading-ask')).not.toBeNull();
    expect(control('reading-ask')?.getAttribute('aria-disabled')).not.toBe('true');
    expect(text('[data-next-ended-goal]')).toContain(
      'your saved intent and the goal drafted from your prompt still can',
    );
    expect(text('[data-next-ended-goal]')).not.toContain('can only read');
  });

  it('keeps Full activity open and held fields across refresh and a remount', async () => {
    const page = mountSession({ store: { goal: 'Saved', lines: ['A check'], revision: 1 } });
    await settle(page);
    const trigger = () => document.querySelector('[data-next-full-activity-trigger]');
    expect(trigger()?.getAttribute('aria-expanded')).toBe('false');
    await act(async () => {
      fireEvent.click(trigger() as Element);
    });
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
