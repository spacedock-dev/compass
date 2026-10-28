import type { Meta, StoryObj } from '@storybook/react-vite';
import { expect, userEvent, waitFor, within } from 'storybook/test';
import { useEffect, useState } from 'react';
import { createShell } from '../src/shell/createShell';
import { ShellContext } from '../src/shell/context';
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
      <SettingsView />
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

const outcome = (canvasElement: HTMLElement) =>
  canvasElement.querySelector('[data-next-settings-outcome]')?.textContent ?? '';

export const EditCheckAndSave: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const prompt = await canvas.findByRole('spinbutton', { name: 'Prompt size (KB)' });
    const kept = canvas.getByRole('spinbutton', { name: 'Messages and checks kept' });
    await expect(canvas.getByRole('heading', { name: 'Settings', level: 1 })).toBeVisible();
    await expect(prompt).toHaveValue(256);
    await expect(kept).toHaveValue(5000);
    await expect(prompt).toHaveAccessibleDescription(
      expect.stringContaining('In force: 256 KB. Default 256 KB. Allowed 16 to 512 KB.'),
    );

    // Out of range: named inline, marked invalid, and Save sends nothing and returns to the field.
    await userEvent.clear(prompt);
    await userEvent.type(prompt, '2048');
    const range = 'Enter a whole number from 16 to 512 KB.';
    await expect(canvas.getByText(range)).toBeVisible();
    await expect(prompt).toHaveAttribute('aria-invalid', 'true');
    await expect(prompt).toHaveAccessibleDescription(expect.stringContaining(range));
    await userEvent.click(canvas.getByRole('button', { name: 'Save' }));
    await expect(posted).toHaveLength(0);
    await expect(prompt).toHaveFocus();
    await expect(outcome(canvasElement)).toBe(
      'Nothing was saved. Correct the value marked below first.',
    );

    // Fixed and saved from the keyboard: only the changed key goes, in bytes.
    await userEvent.clear(prompt);
    await userEvent.type(prompt, '512{Enter}');
    await waitFor(() =>
      expect(outcome(canvasElement)).toBe(
        'Saved. The next Analyze drift press reads with these limits.',
      ),
    );
    await expect(posted).toEqual([{ analyze_prompt_bytes: 524288 }]);
    await expect(canvas.queryByText(range)).toBeNull();
    await expect(prompt).toHaveValue(512);
    await expect(prompt).toHaveAccessibleDescription(
      expect.stringContaining('In force: 512 KB. Default 256 KB.'),
    );
  },
};

export const RestoreDefaults: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const kept = await canvas.findByRole('spinbutton', {
      name: 'Messages and checks kept',
    });
    await expect(kept).toHaveValue(5000);
    // Only the limit that differs from its default offers it back.
    await expect(canvas.getAllByRole('button', { name: /^Restore default/ })).toHaveLength(1);
    await userEvent.click(
      canvas.getByRole('button', { name: 'Restore default (2,000 messages and checks)' }),
    );
    await waitFor(() => expect(kept).toHaveValue(2000));
    await expect(posted).toEqual([{ analyze_record_events: null }]);
    await expect(outcome(canvasElement)).toBe(
      'Messages and checks kept is back to its default, 2,000 messages and checks.',
    );
    await expect(canvas.queryByRole('button', { name: /^Restore default/ })).toBeNull();
    await expect(canvas.queryByRole('button', { name: 'Restore all defaults' })).toBeNull();

    // Save a change, then put every limit back with one press.
    const listed = canvas.getByRole('spinbutton', {
      name: 'Checks and files listed',
    });
    await userEvent.clear(listed);
    await userEvent.type(listed, '400');
    await userEvent.click(canvas.getByRole('button', { name: 'Save' }));
    const all = await canvas.findByRole('button', { name: 'Restore all defaults' });
    await userEvent.click(all);
    await waitFor(() => expect(listed).toHaveValue(200));
    await expect(posted.at(-1)).toEqual({
      analyze_prompt_bytes: null,
      analyze_record_events: null,
      analyze_listed_checks: null,
    });
    await expect(outcome(canvasElement)).toBe('Every limit is back to its default.');
  },
};

export const RefusedSaveKeepsWhatWasTyped: Story = {
  args: { scenario: 'refuses-400' },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const kept = await canvas.findByRole('spinbutton', {
      name: 'Messages and checks kept',
    });
    await userEvent.clear(kept);
    await userEvent.type(kept, '3000');
    await userEvent.click(canvas.getByRole('button', { name: 'Save' }));
    await waitFor(() =>
      expect(outcome(canvasElement)).toBe(
        'The server refused these values, so nothing was saved. Each must be a whole number inside its range.',
      ),
    );
    await expect(posted).toEqual([{ analyze_record_events: 3000 }]);
    await expect(kept).toHaveValue(3000);
    await expect(kept).toHaveAccessibleDescription(
      expect.stringContaining('In force: 5,000 messages and checks.'),
    );
  },
};

export const StoreUnavailable: Story = {
  args: { scenario: 'refuses-503' },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const listed = await canvas.findByRole('spinbutton', {
      name: 'Checks and files listed',
    });
    await userEvent.clear(listed);
    await userEvent.type(listed, '300');
    await userEvent.click(canvas.getByRole('button', { name: 'Save' }));
    await waitFor(() =>
      expect(outcome(canvasElement)).toBe(
        'The settings could not be written, so nothing changed. Try again.',
      ),
    );
    await expect(listed).toHaveValue(300);
  },
};

export const FailedReadThenTryAgain: Story = {
  args: { scenario: 'unreadable-once' },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(
      await canvas.findByText('The settings could not be read, so none are shown.'),
    ).toBeVisible();
    await expect(canvas.queryByRole('spinbutton')).toBeNull();
    const retry = canvas.getByRole('button', { name: 'Try again' });
    retry.focus();
    await userEvent.keyboard('{Enter}');
    await expect(await canvas.findByRole('spinbutton', { name: 'Prompt size (KB)' })).toHaveValue(
      256,
    );
  },
};
