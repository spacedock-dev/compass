import { expect } from 'storybook/test';

export async function atPageWidth(width: number, check: () => Promise<void>) {
  const browserPage =
    '__vitest_browser_runner__' in window ? (await import('vitest/browser')).page : null;
  const before = { width: window.innerWidth, height: window.innerHeight };
  if (browserPage) await browserPage.viewport(width, 800);
  try {
    if (browserPage) await expect(window.innerWidth).toBe(width);
    await check();
    await expect(document.documentElement.scrollWidth).toBe(window.innerWidth);
  } finally {
    if (browserPage) await browserPage.viewport(before.width, before.height);
  }
}
