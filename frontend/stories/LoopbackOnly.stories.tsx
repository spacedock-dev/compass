import type { Meta, StoryObj } from '@storybook/react-vite';
import { expect, userEvent, within } from 'storybook/test';
import { useEffect, useState } from 'react';
import { App } from '../src/App';
import { createRouter } from '../src/router/router';
import { fakeRouterEnvironment } from '../src/router/testing';
import { createShell } from '../src/shell/createShell';
import { createFakeClock, createFakeEnvironment } from '../src/transport/testing';
import { fakeBackend } from '../test/storage_backends';
import { LOOPBACK_ONLY } from '../src/shell/Notices';

function ProxiedPage() {
  const [shell] = useState(() => {
    const history = fakeRouterEnvironment('#n=settings');
    return createShell({
      env: createFakeEnvironment({ clock: createFakeClock() }),
      router: createRouter(history.env),
      provider: () => fakeBackend(),
      events: { addEventListener: () => undefined, removeEventListener: () => undefined },
      search: '',
      doc: null,
      reducedMotion: () => true,
      fetch: async (url, init) => {
        if (init?.method === 'POST')
          return new Response(
            JSON.stringify({
              ok: false,
              reason: 'loopback-only',
              message: 'Server text the page never renders.',
            }),
            { status: 403 },
          );
        return new Response(
          JSON.stringify(
            url === '/api/settings'
              ? {
                  values: { analyze_record_events: 2000 },
                  limits: [
                    { key: 'analyze_record_events', default: 2000, minimum: 100, maximum: 20000 },
                  ],
                }
              : {
                  generated: 1900000000,
                  sessions: [
                    {
                      harness: 'claude',
                      sid: 'proxied',
                      project: 'example/app',
                      state: 'working',
                      title: 'Synthetic proxied session',
                    },
                  ],
                },
          ),
          { status: 200 },
        );
      },
    });
  });
  useEffect(
    () => () => {
      shell.runtime.dispose();
      shell.display.dispose();
    },
    [shell],
  );
  return <App shell={shell} />;
}

const meta = { title: 'Shell/Behind a web proxy', component: ProxiedPage } satisfies Meta<
  typeof ProxiedPage
>;
export default meta;
type Story = StoryObj<typeof meta>;

export const ARefusedActionSaysItNeedsTheComputerRunningCompass: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const sentence = LOOPBACK_ONLY;
    await userEvent.click(await canvas.findByRole('button', { name: 'Customize' }));
    const field = await canvas.findByRole('slider', { name: 'Messages, tests and builds kept' });
    await expect(canvas.queryByText(sentence)).toBeNull();
    await expect(field).toHaveAttribute('aria-valuetext', '2,000');
    field.focus();
    await userEvent.keyboard('{End}');
    await expect(await canvas.findByText(sentence)).toBeVisible();
    await expect(field).toHaveAttribute('aria-valuetext', '2,000');
    await expect(canvas.queryByText('Limits saved.')).toBeNull();
    await expect(canvas.queryByText('Server text the page never renders.')).toBeNull();
    await userEvent.click(canvas.getByRole('heading', { name: 'Settings' }));
    await userEvent.keyboard('s');
    await expect(
      await canvas.findByRole('link', { name: 'Open session Synthetic proxied session' }),
    ).toBeVisible();
    await expect(canvas.getByText(sentence)).toBeVisible();
  },
};
