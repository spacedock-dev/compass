import type { Meta, StoryObj } from '@storybook/react-vite';
import { expect, userEvent, within } from 'storybook/test';
import { useEffect, useState } from 'react';
import { RailUsage } from '../src/capacity/UsageConsent';
import { createShell } from '../src/shell/createShell';
import { ShellContext } from '../src/shell/context';
import { createFakeClock, createFakeEnvironment } from '../src/transport/testing';
import { fakeBackend } from '../test/storage_backends';

/* The quota fetch is on until the reader turns it off: one line says what is read and that no session content
   is sent, and one button turns it off. Every `/api/data` URL the page sends is kept, so the story asserts the
   request a press changes, not only the words. */
const requests: string[] = [];
function QuotaExample({ declined = false }: { readonly declined?: boolean }) {
  const [shell] = useState(() => {
    requests.length = 0;
    let generated = 1;
    const backend = fakeBackend(declined ? { 'compass.next.usage.consent': 'declined' } : {});
    const json = (body: unknown) => new Response(JSON.stringify(body), { status: 200 });
    return createShell({
      env: createFakeEnvironment({ clock: createFakeClock() }),
      provider: () => backend,
      events: { addEventListener: () => undefined, removeEventListener: () => undefined },
      search: '',
      doc: null,
      reducedMotion: () => true,
      fetch: async (url) => {
        if (url.startsWith('/api/data')) requests.push(url);
        return json({ generated: generated++, sessions: [], usage_fetch: true, usage: [] });
      },
    });
  });
  useEffect(() => {
    const release = shell.runtime.acquire();
    void shell.runtime.refresh();
    return () => {
      release();
      shell.runtime.dispose();
      shell.display.dispose();
    };
  }, [shell]);
  return (
    <ShellContext.Provider value={shell}>
      <RailUsage />
    </ShellContext.Provider>
  );
}
const meta = { title: 'Capacity/Quota line', component: QuotaExample } satisfies Meta<
  typeof QuotaExample
>;
export default meta;
type Story = StoryObj<typeof meta>;

export const OnUntilTurnedOff: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(
      await canvas.findByText(
        'Quota is read with the Claude Code and Cursor logins on this machine. No session content is sent.',
      ),
    ).toBeVisible();
    await expect(requests.at(-1)).toMatch(/usage=1/);
    await userEvent.click(canvas.getByRole('button', { name: 'Turn off' }));
    await expect(
      await canvas.findByText(
        'Quota reading is off. Windows above are the last cached read and will lapse.',
      ),
    ).toBeVisible();
    await expect(requests.at(-1)).not.toMatch(/usage=/);
  },
};

export const TurnedOffEarlier: Story = {
  args: { declined: true },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(await canvas.findByRole('button', { name: 'Turn on' })).toBeVisible();
    await expect(requests.every((url) => !/usage=/.test(url))).toBe(true);
    await userEvent.click(canvas.getByRole('button', { name: 'Turn on' }));
    await expect(await canvas.findByRole('button', { name: 'Turn off' })).toBeVisible();
    await expect(requests.at(-1)).toMatch(/usage=1/);
  },
};
