import type { Meta, StoryObj } from '@storybook/react-vite';
import { expect, userEvent, waitFor, within } from 'storybook/test';
import { openInFlow } from './disclosure.flow';
import { GLOSSARY } from '../src/language/glossary';
import { SLOT_LABELS } from '../src/capacity/model';
import { contrastOf, rgbOf } from './a11y.audit';
import {
  CLAUDE_STATUS_LINE_WINDOWS,
  CLAUDE_WINDOW,
  CODEX_WINDOW,
  QuotaExample,
  refreshQuota,
  requests,
} from './quota.scenario';

const meta = { title: 'Capacity/Quota line', component: QuotaExample } satisfies Meta<
  typeof QuotaExample
>;
export default meta;
type Story = StoryObj<typeof meta>;

export const OnUntilTurnedOff: Story = {
  args: { strip: true, usage: CLAUDE_WINDOW },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(
      await canvas.findByText(
        'Quota is read with the Claude Code and Cursor logins on this machine. No session content is sent.',
      ),
    ).toBeVisible();
    await expect(requests.at(-1)).toMatch(/usage=1/);
    await userEvent.click(canvas.getByRole('button', { name: 'Turn off quota reading' }));
    await expect(
      await canvas.findByText('Quota reading is off. The last cached read will lapse.'),
    ).toBeVisible();
    await expect(canvas.queryByRole('progressbar')).toBeNull();
    await expect(requests.at(-1)).not.toMatch(/usage=/);
  },
};

export const TurnedOffEarlier: Story = {
  args: { declined: true, strip: true },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(
      await canvas.findByText('Quota reading is off. No window has been read.'),
    ).toBeVisible();
    await expect(canvas.queryByRole('progressbar')).toBeNull();
    await expect(
      await canvas.findByRole('button', { name: 'Turn on quota reading' }),
    ).toBeVisible();
    await expect(requests.every((url) => !/usage=/.test(url))).toBe(true);
    await userEvent.click(canvas.getByRole('button', { name: 'Turn on quota reading' }));
    await expect(
      await canvas.findByRole('button', { name: 'Turn off quota reading' }),
    ).toBeVisible();
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
    await expect(canvas.queryByRole('progressbar')).toBeNull();
    await expect(canvas.getByRole('button', { name: 'Turn on quota reading' })).toBeVisible();
  },
};

export const TurnedOffWithWindowsShown: Story = {
  args: { declined: true, strip: true, usage: CLAUDE_WINDOW },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(
      await canvas.findByText('Quota reading is off. The last cached read will lapse.'),
    ).toBeVisible();
    await expect(canvas.queryByRole('progressbar')).toBeNull();
    await expect(canvas.getByRole('button', { name: 'Turn on quota reading' })).toBeVisible();
  },
};

export const TurningOffTheFetchKeepsLocalQuota: Story = {
  args: { strip: true, usage: [...CLAUDE_WINDOW, ...CODEX_WINDOW] },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(await canvas.findByRole('button', { name: 'Turn off quota reading' }));
    await expect(await canvas.findByText('71% used')).toBeVisible();
    await expect(
      canvas.getByRole('progressbar', { name: 'Codex 3-hour allowance used' }),
    ).toBeVisible();
    await expect(canvas.getByText('Codex 3-hour plan · resets in 2h 30m.')).toBeVisible();
    await expect(canvas.queryByRole('button', { name: /Read Claude Code/ })).toBeNull();
    await expect(canvas.getByText(/Local readings are still shown/)).toBeVisible();
    await expect(requests.at(-1)).not.toMatch(/usage=/);
  },
};

/* A reader whose Claude login Compass cannot read still sees Claude beside Codex once Claude Code's status
   line has forwarded its two windows, and Turn off quota reading hides them as it hides a fetched figure. */
export const ClaudeFromTheStatusLineBesideCodex: Story = {
  args: { strip: true, usage: [...CLAUDE_STATUS_LINE_WINDOWS, ...CODEX_WINDOW] },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const card = await canvas.findByRole('region', { name: GLOSSARY.aiAllowance.plain });
    const reader = within(card);
    await expect(
      await reader.findByRole('button', { name: 'Read Claude Code 5-hour window' }),
    ).toBeVisible();
    await expect(
      reader.getByRole('button', { name: `Read Claude Code ${SLOT_LABELS.week} window` }),
    ).toBeVisible();
    await expect(reader.getByRole('button', { name: 'Read Codex 3-hour window' })).toBeVisible();
    await userEvent.click(reader.getByRole('button', { name: 'Read Claude Code 5-hour window' }));
    await expect(reader.getByText('Claude Code 5-hour plan · resets in 2h 30m.')).toBeVisible();
    await expect(reader.getByText('38% used')).toBeVisible();
    await userEvent.click(reader.getByRole('button', { name: 'Turn off quota reading' }));
    await expect(await canvas.findByText('71% used')).toBeVisible();
    await expect(canvas.queryByRole('button', { name: /Read Claude Code/ })).toBeNull();
    await expect(canvas.queryByText('38% used')).toBeNull();
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
    await expect(canvas.getByRole('button', { name: 'Turn on quota reading' })).toBeVisible();
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

export const AllowanceAndItsExplanation: Story = {
  args: { strip: true, usage: CLAUDE_WINDOW },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const card = await canvas.findByRole('region', { name: GLOSSARY.aiAllowance.plain });
    const reader = within(card);
    await expect(reader.getByText('Claude Code 5-hour plan · resets in 2h 30m.')).toBeVisible();
    await expect(reader.getByText('34% used')).toBeVisible();
    await expect(
      reader.queryByText(/^(WINDOW|USED|BUDGET AGAINST CLOCK|PACE|BUDGET ENDS|RESETS)$/),
    ).toBeNull();
    const bar = reader.getByRole('progressbar', { name: 'Claude Code 5-hour allowance used' });
    await expect(bar.tagName).toBe('PROGRESS');
    await expect(bar).toHaveAttribute('value', '34');
    await expect(bar).toHaveAttribute(
      'aria-valuetext',
      '34% of budget used, 50% of the window elapsed',
    );
    await expect(bar.parentElement?.querySelector('.next-capacity-tick')).toBeVisible();
    const disclosure = reader.getByRole('button', { name: GLOSSARY.howAiAllowanceWorks.plain });
    const consent = reader.getByRole('button', { name: 'Turn off quota reading' });
    const panel = await openInFlow(disclosure, consent);
    const facts = within(panel);
    for (const name of ['Pace', 'Reset time', 'Window', 'Source'])
      await expect(facts.getByText(name, { exact: true })).toBeVisible();
    const before = requests.length;
    await refreshQuota?.();
    await waitFor(() => expect(requests.length).toBeGreaterThan(before));
    await expect(disclosure).toHaveAttribute('aria-expanded', 'true');
    await expect(facts.getByText('Source', { exact: true })).toBeVisible();
  },
};

const LONG_PROJECT = `service-${'component'.repeat(18)}`;

export const ALongProjectFitsTheOpenAllowanceOnAPhone: Story = {
  args: {
    strip: true,
    usage: CLAUDE_WINDOW,
    history: ['a', 'b'].flatMap((sid) => [
      { sid, harness: 'claude', project: LONG_PROJECT, state: 'working', last_activity: 100 },
      { sid, harness: 'claude', project: LONG_PROJECT, state: 'idle', last_activity: 600 },
    ]),
  },
  play: async ({ canvasElement }) => {
    const browser =
      '__vitest_browser_runner__' in window ? (await import('vitest/browser')).page : null;
    const before = { width: window.innerWidth, height: window.innerHeight };
    if (browser) await browser.viewport(320, 800);
    try {
      const canvas = within(canvasElement);
      const disclosure = await canvas.findByRole('button', {
        name: GLOSSARY.howAiAllowanceWorks.plain,
      });
      await userEvent.click(disclosure);
      const project = await canvas.findByText(LONG_PROJECT);
      await waitFor(() => expect(project).toBeVisible());
      if (browser) {
        await expect(window.innerWidth).toBe(320);
        await expect(document.documentElement.scrollWidth).toBeLessThanOrEqual(320);
        await expect(project.getBoundingClientRect().right).toBeLessThanOrEqual(320);
      }
    } finally {
      if (browser) await browser.viewport(before.width, before.height);
    }
  },
};

export const SelectedWindowHasAVisibleMarker: Story = {
  args: { strip: true, usage: [...CLAUDE_WINDOW, ...CODEX_WINDOW] },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const codex = await canvas.findByRole('button', { name: 'Read Codex 3-hour window' });
    const claude = canvas.getByRole('button', { name: 'Read Claude Code 5-hour window' });
    await userEvent.click(claude);
    for (const [selected, other] of [
      [claude, codex],
      [codex, claude],
    ] as const) {
      await userEvent.click(selected);
      await expect(selected).toHaveAttribute('aria-pressed', 'true');
      await expect(other).toHaveAttribute('aria-pressed', 'false');
      const edge = getComputedStyle(selected);
      await expect(Number.parseFloat(edge.borderLeftWidth)).toBeGreaterThanOrEqual(2);
      await expect(edge.borderLeftWidth).not.toBe(getComputedStyle(other).borderLeftWidth);
      await expect(
        contrastOf(rgbOf(edge.borderLeftColor), rgbOf(edge.backgroundColor)),
      ).toBeGreaterThanOrEqual(3);
    }
  },
};

export const TheEmptyTrackHasAVisibleEdge: Story = {
  args: {
    strip: true,
    usage: [{ harness: 'claude', state: 'ok', fiveH: { pct: 0, windowSec: 18000, resetAt: 9060 } }],
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const card = await canvas.findByRole('region', { name: GLOSSARY.aiAllowance.plain });
    const bar = within(card).getByRole('progressbar');
    await expect(bar).toHaveAttribute('value', '0');
    if (!bar.parentElement) throw new Error('The progress track did not render');
    const edge = getComputedStyle(bar.parentElement);
    await expect(Number.parseFloat(edge.borderTopWidth)).toBeGreaterThanOrEqual(1);
    await expect(
      contrastOf(rgbOf(edge.borderTopColor), rgbOf(getComputedStyle(card).backgroundColor)),
    ).toBeGreaterThanOrEqual(3);
  },
};
