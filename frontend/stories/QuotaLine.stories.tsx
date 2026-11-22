import type { Meta, StoryObj } from '@storybook/react-vite';
import { expect, userEvent, within } from 'storybook/test';
import { useEffect, useState } from 'react';
import { CapacityStrip } from '../src/capacity/CapacityStrip';
import { CapacityPanel } from '../src/delegation/CapacityPanel';
import { observe } from '../src/observed';
import { RailUsage } from '../src/capacity/UsageConsent';
import { createShell } from '../src/shell/createShell';
import { ShellContext } from '../src/shell/context';
import { createFakeClock, createFakeEnvironment } from '../src/transport/testing';
import { fakeBackend } from '../test/storage_backends';
import { contrastOf, rgbOf } from './a11y.audit';

/* The quota fetch is on until the reader turns it off: one line says what is read and that no session content
   is sent, and one button turns it off. Every `/api/data` URL the page sends is kept, so the story asserts the
   request a press changes, not only the words. */
const requests: string[] = [];
const CLAUDE_WINDOW = [
  { harness: 'claude', state: 'ok', asOf: 1, fiveH: { pct: 34, windowSec: 18000, resetAt: 9001 } },
];
function QuotaExample({
  declined = false,
  strip = false,
  rail = false,
  usage = [],
}: {
  readonly declined?: boolean;
  readonly strip?: boolean;
  readonly rail?: boolean;
  readonly usage?: readonly unknown[];
}) {
  const railPayload = { generated: 1, harnesses: [{ key: 'claude', label: 'Claude Code' }], usage };
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
        return json({
          generated: generated++,
          sessions: [],
          harnesses: [{ key: 'claude', label: 'Claude Code' }],
          usage_fetch: true,
          usage,
        });
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
      {strip ? (
        <CapacityStrip />
      ) : rail ? (
        <CapacityPanel
          payload={railPayload}
          model={observe(railPayload)}
          usage={(windows) => <RailUsage windows={windows} />}
        />
      ) : (
        <RailUsage windows />
      )}
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

export const TurnedOffWithNoWindowRead: Story = {
  args: { declined: true, strip: true, usage: [] },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(
      await canvas.findByText('Quota reading is off. No window has been read.'),
    ).toBeVisible();
    await expect(canvas.queryByText(/last cached read/)).toBeNull();
    await expect(canvas.getByRole('button', { name: 'Turn on' })).toBeVisible();
  },
};

export const TurnedOffWithWindowsShown: Story = {
  args: { declined: true, strip: true, usage: CLAUDE_WINDOW },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(
      await canvas.findByText(
        'Quota reading is off. Windows above are the last cached read and will lapse.',
      ),
    ).toBeVisible();
    await expect(canvas.getByRole('button', { name: 'Turn on' })).toBeVisible();
  },
};

export const ConsoleRailTurnedOffWithNoWindowRead: Story = {
  args: { declined: true, rail: true, usage: [] },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(
      await canvas.findByText('Quota reading is off. No window has been read.'),
    ).toBeVisible();
    await expect(canvas.queryByText(/last cached read/)).toBeNull();
    await expect(canvas.getByRole('button', { name: 'Turn on' })).toBeVisible();
  },
};

export const ConsoleRailTurnedOffWithWindowsShown: Story = {
  args: { declined: true, rail: true, usage: CLAUDE_WINDOW },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(
      await canvas.findByText(
        'Quota reading is off. Windows above are the last cached read and will lapse.',
      ),
    ).toBeVisible();
  },
};

const PACE_WINDOWS = [20, 55, 90];
const PACE_USAGE = PACE_WINDOWS.map((pct) => ({
  ...CLAUDE_WINDOW[0],
  fiveH: { pct, windowSec: 18000, resetAt: 9001 },
}));

export const PaceTickContrast: Story = {
  render: () => (
    <>
      <section aria-label="Capacity strip">
        {PACE_USAGE.map((entry) => (
          <QuotaExample key={entry.fiveH.pct} strip usage={[entry]} />
        ))}
      </section>
      <section aria-label="Console capacity rail">
        {PACE_USAGE.map((entry) => (
          <QuotaExample key={entry.fiveH.pct} rail usage={[entry]} />
        ))}
      </section>
    </>
  ),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    for (const [label, prefix] of [
      ['Capacity strip', 'next-capacity'],
      ['Console capacity rail', 'next-rail-capacity'],
    ] as const) {
      const region = within(canvas.getByRole('region', { name: label }));
      for (const pct of PACE_WINDOWS) {
        const bar = await region.findByRole('img', { name: new RegExp(`^${pct}%`) });
        const fill = bar.querySelector(`.${prefix}-fill`);
        const tick = bar.querySelector(`.${prefix}-tick`);
        if (!fill || !tick) throw new Error(`Expected fill and clock tick for ${label} at ${pct}%`);
        const track = bar.getBoundingClientRect();
        const tickBox = tick.getBoundingClientRect();
        await expect(tickBox.left - track.left).toBeCloseTo(track.width / 2, 0);
        const coversTick = fill.getBoundingClientRect().right > tickBox.left + tickBox.width / 2;
        await expect(coversTick).toBe(pct > 50);

        const adjacent = rgbOf(getComputedStyle(coversTick ? fill : bar).backgroundColor);
        const style = getComputedStyle(tick);
        const body = contrastOf(rgbOf(style.backgroundColor), adjacent);
        const edge =
          style.outlineStyle === 'solid' && Number.parseFloat(style.outlineWidth) >= 1
            ? contrastOf(rgbOf(style.outlineColor), adjacent)
            : 0;
        await expect(Math.max(body, edge), `${label} tick at ${pct}% used`).toBeGreaterThanOrEqual(
          3,
        );
      }
    }
  },
};
