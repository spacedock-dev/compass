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

/* Widens the story's viewport for a layout measure and hands back the restore. The default test viewport is
   narrower than the 540px `--measure`, where a capped and an uncapped panel draw the same. */
export async function atWidth(width: number) {
  const driver =
    '__vitest_browser_runner__' in window ? (await import('vitest/browser')).page : null;
  const before = { width: window.innerWidth, height: window.innerHeight };
  if (driver) await driver.viewport(width, 900);
  return async () => {
    if (driver) await driver.viewport(before.width, before.height);
  };
}

/* An opened panel's prose reaches the panel's right edge rather than stopping at the page's reading cap. */
export async function expectSpansPanel(text: HTMLElement, panel: HTMLElement) {
  await waitFor(() => {
    const line = text.getBoundingClientRect();
    const box = panel.getBoundingClientRect();
    expect(line.width, 'the panel has room past the reading cap').toBeGreaterThan(0);
    expect(Math.abs(line.right - box.right), 'the text reaches the panel edge').toBeLessThanOrEqual(
      1,
    );
  });
}
