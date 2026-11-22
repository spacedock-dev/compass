import type { Meta, StoryObj } from '@storybook/react-vite';
import { expect, userEvent, within } from 'storybook/test';
import { useEffect, useState } from 'react';
import { createRouter } from '../src/router/router';
import { fakeRouterEnvironment } from '../src/router/testing';
import { ShellContext } from '../src/shell/context';
import { createShell } from '../src/shell/createShell';
import { Card, SummaryFilterCard, SummaryRouteCard } from '../src/ui/card';
import { auditContrast, formatFailures } from './a11y.audit';
const meta = { title: 'UI/Card', component: Card } satisfies Meta<typeof Card>;
export default meta;
type Story = StoryObj<typeof meta>;

export const Base: Story = {
  args: {
    as: 'article',
    'aria-label': 'Session details',
    children: 'A session is waiting on you.',
  },
  play: async ({ canvasElement }) => {
    const card = within(canvasElement).getByRole('article', { name: 'Session details' });
    await expect(card).toHaveStyle({
      borderWidth: '1px',
      borderLeftWidth: '1px',
      borderRadius: '16px',
      boxShadow: 'none',
      padding: '24px',
    });
  },
};

function SummaryCardsExample() {
  const [working, setWorking] = useState(false);
  const [shell] = useState(() =>
    createShell({
      router: createRouter(fakeRouterEnvironment('#n=sessions').env),
      doc: null,
    }),
  );
  useEffect(
    () => () => {
      shell.runtime.dispose();
      shell.display.dispose();
    },
    [shell],
  );
  return (
    <ShellContext value={shell}>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 16 }}>
        <SummaryRouteCard route={{ view: 'attention' }} cue="Open in Needs you">
          <span>Waiting on you</span>
        </SummaryRouteCard>
        <SummaryFilterCard
          controls="summary-sessions"
          pressed={working}
          onClick={() => setWorking(!working)}
        >
          <span>Working now</span>
        </SummaryFilterCard>
      </div>
      <ul id="summary-sessions">
        <li>Update the onboarding guide</li>
        {!working && <li>Fix the flaky sign-in test</li>}
      </ul>
    </ShellContext>
  );
}

export const SummaryCards: Story = {
  render: () => <SummaryCardsExample />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const route = canvas.getByRole('link', { name: /Open in Needs you/ });
    const filter = canvas.getByRole('button', { name: /Show in the list below/ });
    await expect(route).toHaveAttribute('href', '#n=attention');
    await expect(route.querySelector('[data-icon="go-to-page"]')).toBeVisible();
    await expect(filter.querySelector('[data-icon="show-below"]')).toBeVisible();
    await expect(filter).toHaveAttribute('aria-controls', canvas.getByRole('list').id);
    for (const card of [route, filter]) {
      const box = card.getBoundingClientRect();
      await expect(box.width).toBeGreaterThanOrEqual(44);
      await expect(box.height).toBeGreaterThanOrEqual(44);
    }
    if ('__vitest_browser_runner__' in window) {
      const { page } = await import('vitest/browser');
      const edge = (card: HTMLElement) => {
        const style = getComputedStyle(card);
        return [style.borderTopColor, style.boxShadow];
      };
      const resting = edge(route);
      await page.getByRole('link', { name: /Open in Needs you/ }).hover();
      const hovered = edge(route);
      await expect(hovered[0]).not.toBe(resting[0]);
      await expect(hovered[1]).not.toBe('none');
      await page.getByRole('button', { name: /Show in the list below/ }).hover();
      await expect(edge(filter)).toEqual(hovered);
    }
    await expect(filter).toHaveAttribute('aria-pressed', 'false');
    await userEvent.click(filter);
    await expect(filter).toHaveAttribute('aria-pressed', 'true');
    await expect(filter.querySelector('[data-icon="check"]')).toBeVisible();
    await expect(canvas.queryByText('Fix the flaky sign-in test')).toBeNull();
    const selected = auditContrast(canvasElement);
    await expect(selected.failures, formatFailures(selected)).toEqual([]);
    await userEvent.click(filter);
    await expect(filter).toHaveAttribute('aria-pressed', 'false');
    await expect(canvas.getByText('Fix the flaky sign-in test')).toBeVisible();
  },
};
export const SessionRow: Story = {
  args: { variant: 'session-row', children: 'Card session-row' },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText(args.children as string)).toBeVisible();
  },
};
export const SessionCurrent: Story = {
  args: { variant: 'session-current', children: 'Card session-current' },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText(args.children as string)).toBeVisible();
  },
};
export const SessionAsk: Story = {
  args: { variant: 'session-ask', children: 'Card session-ask' },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText(args.children as string)).toBeVisible();
  },
};
export const SessionLanded: Story = {
  args: { variant: 'session-landed', children: 'Card session-landed' },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText(args.children as string)).toBeVisible();
  },
};
export const IntentRow: Story = {
  args: { variant: 'intent-row', children: 'Card intent-row' },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText(args.children as string)).toBeVisible();
  },
};
export const IntentPanel: Story = {
  args: { variant: 'intent-panel', children: 'Card intent-panel' },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText(args.children as string)).toBeVisible();
  },
};
export const DriftPanel: Story = {
  args: { variant: 'drift-panel', children: 'Card drift-panel' },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText(args.children as string)).toBeVisible();
  },
};
export const ReadingJob: Story = {
  args: { variant: 'reading-job', children: 'Card reading-job' },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText(args.children as string)).toBeVisible();
  },
};
export const ReadingNotice: Story = {
  args: { variant: 'reading-notice', children: 'Card reading-notice' },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText(args.children as string)).toBeVisible();
  },
};
export const ReadingStale: Story = {
  args: { variant: 'reading-stale', children: 'Card reading-stale' },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText(args.children as string)).toBeVisible();
  },
};
export const SteerBox: Story = {
  args: { variant: 'steer-box', children: 'Card steer-box' },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText(args.children as string)).toBeVisible();
  },
};
export const SteerReceipt: Story = {
  args: { variant: 'steer-receipt', children: 'Card steer-receipt' },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText(args.children as string)).toBeVisible();
  },
};
export const ProjectRow: Story = {
  args: { variant: 'project-row', children: 'Card project-row' },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText(args.children as string)).toBeVisible();
  },
};
export const ProjectGoal: Story = {
  args: { variant: 'project-goal', children: 'Card project-goal' },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText(args.children as string)).toBeVisible();
  },
};
export const ProjectRecovery: Story = {
  args: { variant: 'project-recovery', children: 'Card project-recovery' },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText(args.children as string)).toBeVisible();
  },
};
export const CourseRow: Story = {
  args: { variant: 'course-row', children: 'Card course-row' },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText(args.children as string)).toBeVisible();
  },
};
export const StageRule: Story = {
  args: { variant: 'stage-rule', children: 'Card stage-rule' },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText(args.children as string)).toBeVisible();
  },
};
export const RailPanel: Story = {
  args: { variant: 'rail-panel', children: 'Card rail-panel' },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText(args.children as string)).toBeVisible();
  },
};
export const RailWait: Story = {
  args: { variant: 'rail-wait', children: 'Card rail-wait' },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText(args.children as string)).toBeVisible();
  },
};
export const TimelineDetails: Story = {
  args: { variant: 'timeline-details', children: 'Card timeline-details' },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText(args.children as string)).toBeVisible();
  },
};
export const TerminalFrame: Story = {
  args: { variant: 'terminal-frame', children: 'Card terminal-frame' },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText(args.children as string)).toBeVisible();
  },
};
export const AttentionBrief: Story = {
  args: { variant: 'attention-brief', children: 'Card attention-brief' },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText(args.children as string)).toBeVisible();
  },
};
export const AttentionItem: Story = {
  args: { variant: 'attention-item', children: 'Card attention-item' },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText(args.children as string)).toBeVisible();
  },
};
export const CapacityBand: Story = {
  args: { variant: 'capacity-band', children: 'Card capacity-band' },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText(args.children as string)).toBeVisible();
  },
};
export const CapacityProspect: Story = {
  args: { variant: 'capacity-prospect', children: 'Card capacity-prospect' },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText(args.children as string)).toBeVisible();
  },
};
export const QuotaConsent: Story = {
  args: { variant: 'quota-consent', children: 'Card quota-consent' },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText(args.children as string)).toBeVisible();
  },
};
export const ObserverControls: Story = {
  args: { variant: 'observer-controls', children: 'Card observer-controls' },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText(args.children as string)).toBeVisible();
  },
};
export const WorkPanel: Story = {
  args: { variant: 'work-panel', children: 'Card work-panel' },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText(args.children as string)).toBeVisible();
  },
};
export const ToneUnknown: Story = {
  args: {
    variant: 'session-current',
    tone: 'unknown',
    as: 'article',
    'aria-label': 'Current session',
    children: 'Current session',
  },
  play: async ({ canvasElement }) => {
    await expect(
      within(canvasElement).getByRole('article', { name: 'Current session' }),
    ).toBeVisible();
  },
};
export const ToneWant: Story = {
  args: {
    variant: 'session-current',
    tone: 'want',
    as: 'article',
    'aria-label': 'Current session',
    children: 'Current session',
  },
  play: async ({ canvasElement }) => {
    await expect(
      within(canvasElement).getByRole('article', { name: 'Current session' }),
    ).toBeVisible();
  },
};
export const ToneBad: Story = {
  args: {
    variant: 'session-current',
    tone: 'bad',
    as: 'article',
    'aria-label': 'Current session',
    children: 'Current session',
  },
  play: async ({ canvasElement }) => {
    await expect(
      within(canvasElement).getByRole('article', { name: 'Current session' }),
    ).toBeVisible();
  },
};
export const ToneOk: Story = {
  args: {
    variant: 'session-current',
    tone: 'ok',
    as: 'article',
    'aria-label': 'Current session',
    children: 'Current session',
  },
  play: async ({ canvasElement }) => {
    await expect(
      within(canvasElement).getByRole('article', { name: 'Current session' }),
    ).toBeVisible();
  },
};
