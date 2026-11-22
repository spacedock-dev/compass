import type { Meta, StoryObj } from '@storybook/react-vite';
import { expect, userEvent, waitFor, within } from 'storybook/test';
import { openInFlow } from './disclosure.flow';
import { GLOSSARY } from '../src/language/glossary';
import { CLAUDE_WINDOW, QuotaExample, refreshQuota, requests } from './quota.scenario';

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
      await canvas.findByText(
        'Quota reading is off. Windows above are the last cached read and will lapse.',
      ),
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
      await canvas.findByText(
        'Quota reading is off. Windows above are the last cached read and will lapse.',
      ),
    ).toBeVisible();
    await expect(canvas.queryByRole('progressbar')).toBeNull();
    await expect(canvas.getByRole('button', { name: 'Turn on quota reading' })).toBeVisible();
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
