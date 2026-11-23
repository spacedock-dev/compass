import { writeFile } from 'node:fs/promises';
import { registerHooks } from 'node:module';
import { resolve } from 'node:path';

// Substitute the page and its server so the proof scripts can reach their
// capture calls even when a redesigned control breaks an older UI assertion.
registerHooks({
  resolve(specifier, context, nextResolve) {
    if (
      [
        '@playwright/test',
        './intent-board.mjs',
        './support/browser.mjs',
        './browser.mjs',
        './support/world.mjs',
      ].includes(specifier)
    )
      return { url: import.meta.url, shortCircuit: true };
    return nextResolve(specifier, context);
  },
});

const idle = () => undefined;
export const REPOSITORY = resolve('.');
export const chromium = { launch: () => ({ close: idle }) };
export const startIntentBoard = () => ({
  react: {
    origin: 'data:application/json,{"generated":1795392000}#',
  },
  close: idle,
});
function unexpectedBackendAction() {
  throw new Error('The artifact check uses no backend');
}
export const call = unexpectedBackendAction;
export const freePorts = unexpectedBackendAction;
export const refreshReact = unexpectedBackendAction;
export const startReactWorld = unexpectedBackendAction;

export function openPage(_browser, _origins, { viewport: initial }) {
  let viewport = initial;
  return {
    context: { addInitScript: idle, route: idle },
    close: async () => undefined,
    page: {
      goto: idle,
      waitForFunction: idle,
      waitForSelector: idle,
      waitForTimeout: idle,
      setViewportSize: (next) => {
        viewport = next;
      },
      locator: () => ({
        waitFor: idle,
        click: idle,
        fill: idle,
        getAttribute: (name) => (name === 'data-variant' ? 'primary' : null),
      }),
      evaluate(read) {
        const source = String(read);
        if (source.includes('inFirstView'))
          return Array.from({ length: 14 }, () => ({ inFirstView: false }));
        if (source.includes('const box')) {
          const wide = viewport.width === 1280;
          return {
            goal: { top: 0, bottom: 40 },
            primary: { top: 40, bottom: 80 },
            panel: { top: 0, bottom: 100, left: wide ? 500 : 0 },
            activity: { top: wide ? 0 : 100, right: 500 },
            ...viewport,
            scroll: viewport.width,
          };
        }
        if (source.includes('cardClient'))
          return { scroll: viewport.width, client: viewport.width, card: 0, cardClient: 0 };
        if (source.includes('scrollTo')) return undefined;
        return {};
      },
      screenshot: ({ path }) => writeFile(path, `Synthetic screenshot at ${viewport.width}px`),
      getByRole() {
        throw new Error('First-view captures completed');
      },
    },
  };
}
