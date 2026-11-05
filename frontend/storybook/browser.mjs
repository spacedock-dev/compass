import { openPage } from '../e2e/support/browser.mjs';

export function openDevelopmentStorybookPage(browser, origin) {
  return openPage(browser, origin, { nativeWebSockets: true });
}

export function waitForDevelopmentStorybookReady(page) {
  return page.waitForFunction(() => {
    // Storybook's Channel.last records an event after its synchronous store listeners have run.
    const [state] =
      globalThis.__STORYBOOK_ADDONS_CHANNEL__?.last('UNIVERSAL_STORE:storybook/test') ?? [];
    return (
      state?.event?.type === '__EXISTING_STATE_RESPONSE' &&
      state.eventInfo?.actor?.type === 'LEADER' &&
      state.eventInfo.actor.environment === 'SERVER'
    );
  });
}
