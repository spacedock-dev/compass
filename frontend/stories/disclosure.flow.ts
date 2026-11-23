import { expect, userEvent, waitFor } from 'storybook/test';

export async function openInFlow(trigger: HTMLElement, following: HTMLElement) {
  await expect(trigger).toHaveAttribute('aria-expanded', 'false');
  await expect(trigger.getBoundingClientRect().height).toBeGreaterThanOrEqual(44);
  const before = following.getBoundingClientRect().top + window.scrollY;
  await userEvent.click(trigger);
  const panel = document.getElementById(trigger.getAttribute('aria-controls') ?? '');
  if (!panel) throw new Error('The expanded button has no panel');
  await waitFor(() => {
    expect(panel).toBeVisible();
    const bounds = panel.getBoundingClientRect();
    expect(bounds.height).toBeGreaterThan(0);
    expect(bounds.top).toBeGreaterThanOrEqual(trigger.getBoundingClientRect().bottom - 1);
    expect(following.getBoundingClientRect().top + window.scrollY).toBeGreaterThan(before);
    expect(following.getBoundingClientRect().top).toBeGreaterThanOrEqual(bounds.bottom - 1);
  });
  return panel;
}
