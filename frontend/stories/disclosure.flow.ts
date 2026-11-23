import { expect, userEvent, waitFor } from 'storybook/test';
import { settledLayout } from './settled-layout';

export async function openInFlow(trigger: HTMLElement, following: HTMLElement) {
  await expect(trigger).toHaveAttribute('aria-expanded', 'false');
  await expect(trigger.getBoundingClientRect().height).toBeGreaterThanOrEqual(44);
  const documentTop = () =>
    settledLayout(() => following.getBoundingClientRect().top + window.scrollY);
  const before = await documentTop();
  await userEvent.click(trigger);
  const panel = document.getElementById(trigger.getAttribute('aria-controls') ?? '');
  if (!panel) throw new Error('The expanded button has no panel');
  await waitFor(async () => {
    expect(panel).toBeVisible();
    const bounds = panel.getBoundingClientRect();
    expect(bounds.height).toBeGreaterThan(0);
    expect(bounds.top).toBeGreaterThanOrEqual(trigger.getBoundingClientRect().bottom - 1);
    expect(await documentTop()).toBeGreaterThan(before);
    expect(following.getBoundingClientRect().top).toBeGreaterThanOrEqual(bounds.bottom - 1);
  });
  return panel;
}
