import { openPage } from '../e2e/support/browser.mjs';

export function openDevelopmentStorybookPage(browser, origin) {
  return openPage(browser, origin, { nativeWebSockets: true });
}
