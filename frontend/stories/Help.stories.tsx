import type { Meta, StoryObj } from '@storybook/react-vite';
import { expect, userEvent, waitFor, within } from 'storybook/test';
import { EXPLANATIONS, GLOSSARY, SESSION_ROW_WORDS } from '../src/language/glossary';
import { HeaderExample } from './Header.stories';
import { atPageWidth } from './PageFit';

const meta = {
  title: 'Help',
  component: HeaderExample,
  args: { fragment: '#n=help' },
  parameters: { layout: 'fullscreen' },
} satisfies Meta<typeof HeaderExample>;
export default meta;
type Story = StoryObj<typeof meta>;

export const Guide: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByRole('heading', { level: 1 })).toHaveTextContent('How Compass works');
    const nav = within(canvas.getByRole('navigation', { name: 'Primary' }));
    await expect(nav.getAllByRole('link').at(-1)).toBe(
      nav.getByRole('link', { name: 'Help', current: 'page' }),
    );
    const legend = within(canvas.getByRole('list', { name: 'Session icons' }));
    const words = SESSION_ROW_WORDS;
    const rows = legend.getAllByRole('listitem');
    await expect(rows.map((row) => row.querySelector('strong')?.textContent)).toEqual([
      words.working,
      words.waitingOnYou,
      words.quiet,
      words.ended,
      words.worthALook,
    ]);
    await expect(rows[2]?.querySelector('[data-icon="quiet"]')).toBeVisible();
    await expect(rows[2]).toHaveTextContent(
      'The agent finished its turn and is waiting for your next message.',
    );
    await expect(rows[3]).toHaveTextContent('The session reported that it ended.');
    const progress = within(canvas.getByRole('region', { name: 'Goals and progress checks' }));
    for (const word of [
      GLOSSARY.onTrack.plain,
      words.slightlyOffCourse,
      words.offCourse,
      words.wayOffCourse,
    ])
      await expect(progress.getByText(word, { exact: true })).toBeVisible();
    await expect(
      progress.getByText('No departure found in what Compass read', { exact: true }),
    ).toBeVisible();
    for (const [word, explanation] of [
      [
        words.noGoalYet,
        'Open the session and add a goal there to give Compass something to read against.',
      ],
      [words.notCheckedYet, 'Check progress to ask Compass to read the record against the goal.'],
      [words.tooEarlyToTell, 'The session has recorded too little for a reading.'],
      [
        words.cantTell,
        'What Compass read found no departure and gives too little evidence to say the goal was met.',
      ],
      [words.goalTooVague, 'Say what should be true when the work is done.'],
      [words.outOfDate, 'The earlier reading no longer describes the evidence Compass can use.'],
    ]) {
      const term = progress.getByText(word ?? '', { exact: true });
      await expect(term).toBeVisible();
      await expect(term.parentElement?.querySelector('svg')).toBeNull();
      await expect(term.nextElementSibling?.textContent).toBe(explanation);
    }
    for (const question of [
      'What gets sent to an AI, and where?',
      'Which agents can Compass see?',
      'Why are some sessions in an Unnamed folder?',
      EXPLANATIONS.aiAllowance,
    ])
      await userEvent.click(canvas.getByRole('button', { name: question }));
    for (const link of canvas.getAllByRole('link'))
      await expect(link.getAttribute('href')).toMatch(/^#n=/);
  },
};

export const SupportedAgents: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole('button', { name: 'Which agents can Compass see?' }));
    await waitFor(() =>
      expect(
        canvas.getByText(
          'Antigravity CLI, Claude Code, Codex, GitHub Copilot CLI, Cursor CLI, Factory Droid, Gemini CLI, Goose, OpenCode, Pi.',
          { exact: true },
        ),
      ).toBeVisible(),
    );
    await expect(
      within(canvas.getByRole('region', { name: 'Common questions' })).getByRole('link', {
        name: /^Needs you$/,
      }),
    ).toBeVisible();
  },
};

export const GoalExplainer: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const explanation = /Give the goal and, if useful/;
    await expect(canvas.queryByText(explanation)).toBeNull();
    await userEvent.click(canvas.getByRole('link', { name: EXPLANATIONS.goals }));
    await expect(await canvas.findByText(explanation)).toBeVisible();
    await expect(canvas.getAllByText(explanation)).toHaveLength(1);
    const crumb = within(canvas.getByRole('navigation', { name: 'Breadcrumb' }));
    await expect(crumb.getByRole('link', { name: 'Help' })).toHaveAttribute('href', '#n=help');
    await userEvent.click(crumb.getByRole('link', { name: 'Help' }));
    await expect(await canvas.findByRole('heading', { name: 'How Compass works' })).toBeVisible();
  },
};

function fit(width: number): Story {
  return {
    play: async ({ canvasElement }) => {
      await atPageWidth(width, async () => {
        await expect(within(canvasElement).getByRole('heading', { level: 1 })).toBeVisible();
      });
    },
  };
}

export const Fits390 = fit(390);
export const Fits375 = fit(375);
export const Fits320 = fit(320);

export const ReadingWidth: Story = {
  play: async ({ canvasElement }) => {
    await atPageWidth(1280, async () => {
      const heading = within(canvasElement).getByRole('heading', { name: 'How Compass works' });
      const page = heading.closest('[data-next-view-body="help"]');
      await expect(page?.getBoundingClientRect().width).toBe(920);
    });
  },
};
