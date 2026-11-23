import type { Meta, StoryObj } from '@storybook/react-vite';
import { expect, userEvent, within } from 'storybook/test';
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
    for (const word of [
      words.noGoalYet,
      words.notCheckedYet,
      words.tooEarlyToTell,
      words.cantTell,
      words.goalTooVague,
      words.outOfDate,
    ]) {
      const term = progress.getByText(word, { exact: true });
      await expect(term).toBeVisible();
      await expect(term.parentElement?.querySelector('svg')).toBeNull();
      await expect(term.nextElementSibling).toHaveTextContent(/\S/);
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
