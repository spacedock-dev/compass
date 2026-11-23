import type { Meta, StoryObj } from '@storybook/react-vite';
import { expect, userEvent, waitFor, within } from 'storybook/test';
import { useEffect, useState } from 'react';
import { createShell } from '../src/shell/createShell';
import { ShellContext } from '../src/shell/context';
import { ControlsProvider } from '../src/controls';
import { SettingsView } from '../src/settings';
import { createFakeClock, createFakeEnvironment } from '../src/transport/testing';
import { fakeBackend } from '../test/storage_backends';

/* The Settings screen on the real shell and client, over a scripted server that answers as
   `/api/settings` does: the values in force and each limit's default and bounds, and an HTML refusal
   for a write it will not take. */

const LIMITS = [
  { key: 'analyze_prompt_bytes', default: 262144, minimum: 16384, maximum: 524288 },
  { key: 'analyze_record_events', default: 2000, minimum: 100, maximum: 20000 },
  { key: 'analyze_listed_checks', default: 200, minimum: 12, maximum: 2000 },
];
const DEFAULTS: Record<string, number> = {
  analyze_prompt_bytes: 262144,
  analyze_record_events: 2000,
  analyze_listed_checks: 200,
};

type Scenario = 'accepts' | 'refuses-400' | 'refuses-503' | 'unreadable-once';
const posted: unknown[] = [];

function SettingsExample({ scenario }: { readonly scenario: Scenario }) {
  const [shell] = useState(() => {
    posted.length = 0;
    const store = { ...DEFAULTS, analyze_record_events: 5000 };
    let reads = 0;
    const backend = fakeBackend();
    const json = (body: unknown) => new Response(JSON.stringify(body), { status: 200 });
    return createShell({
      env: createFakeEnvironment({ clock: createFakeClock() }),
      provider: () => backend,
      events: { addEventListener: () => undefined, removeEventListener: () => undefined },
      search: '',
      doc: null,
      reducedMotion: () => true,
      fetch: async (url, init) => {
        if (url === '/api/health') return json({ port: 6226 });
        if (url !== '/api/settings') return json({ generated: 1, sessions: [] });
        if (init?.method !== 'POST') {
          reads += 1;
          if (scenario === 'unreadable-once' && reads === 1)
            return new Response('', { status: 500 });
          return json({ values: store, limits: LIMITS });
        }
        const { values } = JSON.parse(String(init.body)) as {
          values: Record<string, number | null>;
        };
        posted.push(values);
        if (scenario === 'refuses-400')
          return new Response('<html>outside its bounds</html>', { status: 400 });
        if (scenario === 'refuses-503')
          return new Response('<html>could not be written</html>', { status: 503 });
        for (const [key, value] of Object.entries(values))
          store[key as keyof typeof store] = value ?? (DEFAULTS[key] as number);
        return json({ values: store, limits: LIMITS });
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
  return (
    <ShellContext.Provider value={shell}>
      <ControlsProvider controls={shell.controls}>
        <SettingsView />
      </ControlsProvider>
    </ShellContext.Provider>
  );
}

const meta = {
  title: 'Views/Settings',
  component: SettingsExample,
  args: { scenario: 'accepts' },
} satisfies Meta<typeof SettingsExample>;
export default meta;
type Story = StoryObj<typeof meta>;

export const ForgetEverythingInline: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const card = within(canvas.getByRole('region', { name: 'Your data' }));
    await expect(
      canvas.getByRole('region', { name: 'Your data' }).querySelector('svg[data-icon="forget"]'),
    ).not.toBeNull();
    const trigger = card.getByRole('button', { name: 'Forget everything' });
    await expect(trigger).toHaveAttribute('aria-expanded', 'false');
    await userEvent.click(trigger);
    await expect(trigger).toHaveAttribute('aria-expanded', 'true');
    await waitFor(() => expect(card.getByText('This cannot be undone.')).toBeVisible());
    const stop = await card.findByText('spacedock-compass --port 6226 --stop');
    const forget = card.getByText('spacedock-compass --port 6226 --forget');
    await expect(
      stop.compareDocumentPosition(forget) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    await expect(card.getByRole('list', { name: 'Deletes' })).toBeVisible();
    await expect(card.getByRole('list', { name: 'Keeps' })).toBeVisible();
    await expect(
      canvasElement.querySelector('[role="dialog"], [role="alertdialog"], [aria-modal]'),
    ).toBeNull();
    await expect(card.queryByRole('button', { name: 'Done' })).toBeNull();
  },
};
