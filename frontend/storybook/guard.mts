import { defineBrowserCommand } from '@vitest/browser-playwright';
import { readFonts } from '../build/package.mjs';
import { fileURLToPath } from 'node:url';
import type { Page } from 'playwright';
const logs = new WeakMap<Page, string[]>();
export const storyGuard = defineBrowserCommand(async ({ page, context }) => {
  if (!logs.has(page)) {
    page.on('console', (message) => {
      if (message.type() === 'error') logs.get(page)?.push(message.text());
    });
    page.on('pageerror', (error) => logs.get(page)?.push(error.message));
    await context.route('**/*', (route) => {
      const url = new URL(route.request().url());
      if (['data:', 'blob:'].includes(url.protocol) || url.hostname === '127.0.0.1')
        return route.continue();
      logs.get(page)?.push(`External request: ${url.href}`);
      return route.abort();
    });
    await context.routeWebSocket('**/*', (socket) => {
      if (new URL(socket.url()).hostname === '127.0.0.1') return socket.connectToServer();
      logs.get(page)?.push(`External socket: ${socket.url()}`);
      socket.close();
    });
  }
  logs.set(page, []);
  return (await readFonts(fileURLToPath(new URL('../../', import.meta.url)))).css;
});
export const storyResult = defineBrowserCommand(async ({ page }) => logs.get(page) ?? []);
export const storyForcedColors = defineBrowserCommand(
  async ({ page }, forcedColors: 'active' | 'none' | null) => {
    await page.emulateMedia({ forcedColors });
  },
);
