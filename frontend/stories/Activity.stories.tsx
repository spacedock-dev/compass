import type { Meta, StoryObj } from '@storybook/react-vite';
import { expect, userEvent, within, waitFor } from 'storybook/test';
import { useState } from 'react';
import { ActivityMarks } from '../src/drift/ActivityMarks';
import { ActivityHead } from '../src/drift/ActivityHead';
import { CheckRun } from '../src/drift/CheckRun';
import { activityRow } from '../src/drift/activity.test.helper';
import {
  foldRuns,
  lastTurnLead,
  MARK_LEGEND,
  plainEmphasis,
  rowsByNumber,
  type WorkRow,
} from '../src/drift/workList';
import { TooltipProvider } from '../src/ui/tooltip';
import '../src/drift/drift.css';

const meta = {
  title: 'Drift/Activity',
  component: ActivityMarks,
  args: { marks: MARK_LEGEND },
} satisfies Meta<typeof ActivityMarks>;
export default meta;
type Story = StoryObj<typeof meta>;
export const Marks: Story = {
  render: () => (
    <TooltipProvider delay={0}>
      <ActivityMarks marks={MARK_LEGEND} />
    </TooltipProvider>
  ),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    for (const mark of MARK_LEGEND) {
      const trigger = canvas.getByLabelText(mark.words);
      await expect(trigger).toBeVisible();
      await expect(trigger.tagName).toBe('SPAN');
      await expect(trigger.tabIndex).toBe(-1);
      await expect(trigger).toHaveAttribute('data-activity-mark', mark.icon);
      await expect(trigger.querySelector('svg')).toHaveAttribute('data-icon', mark.icon);
      if (mark.short) await expect(trigger).toHaveTextContent(mark.short);
      await userEvent.hover(trigger);
      const tooltip = await within(canvasElement.ownerDocument.body).findByRole('tooltip');
      await expect(tooltip).toHaveTextContent(mark.words);
      await userEvent.unhover(trigger);
      await waitFor(() =>
        expect(
          within(canvasElement.ownerDocument.body).queryByRole('tooltip'),
        ).not.toBeInTheDocument(),
      );
    }
    const unknown = canvas.getByLabelText('Ran, result not recorded');
    await expect(unknown.querySelector('path')).toHaveAttribute(
      'd',
      'M128,24A104,104,0,1,0,232,128,104.11,104.11,0,0,0,128,24Zm0,192a88,88,0,1,1,88-88A88.1,88.1,0,0,1,128,216Z',
    );
    await expect(unknown.querySelector('polyline')).toBeNull();
    const style = getComputedStyle(unknown);
    // The muted absence ink on the dark panel is shared with the record's captions.
    await expect(style.color).toBe('rgb(205, 199, 180)');
  },
};

function RunExample({ rows }: { rows: readonly WorkRow[] }) {
  const [open, setOpen] = useState(false);
  return (
    <TooltipProvider delay={0}>
      <div role="list">
        {foldRuns(rows).map((item) =>
          item.kind === 'row' ? (
            <div key={item.row.entry.id} data-story-entry={item.row.entry.id} role="listitem">
              <ActivityHead row={item.row} />
              <p>{item.row.entry.summary}</p>
            </div>
          ) : (
            <CheckRun key={item.last.entry.id} run={item} open={open} onOpenChange={setOpen}>
              {item.rows.map((row) => (
                <div key={row.entry.id} data-story-entry={row.entry.id} role="listitem">
                  <ActivityHead row={row} />
                  <p>{row.entry.summary}</p>
                </div>
              ))}
            </CheckRun>
          ),
        )}
      </div>
    </TooltipProvider>
  );
}
export const Fold: Story = {
  render: () => <RunExample rows={[3, 2, 1].map((n) => activityRow(n))} />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const trigger = canvas.getByRole('button', { name: /3 checks/ });
    await expect(trigger).toHaveAttribute('aria-expanded', 'false');
    await expect(trigger.getBoundingClientRect().height).toBeGreaterThanOrEqual(44);
    await expect(trigger).toHaveTextContent('3 no result');
    await expect(trigger).toHaveTextContent('#1 to #3');
    await expect(trigger).toHaveTextContent('97s to 99s ago');
    await expect(canvas.getByText('check 1')).not.toBeVisible();
    await userEvent.click(trigger);
    await expect(trigger).toHaveAttribute('aria-expanded', 'true');
    await waitFor(() => expect(canvas.getByText('check 1')).toBeVisible());
    await expect(
      [...canvasElement.querySelectorAll<HTMLElement>('[data-story-entry]')].map(
        (row) => row.dataset['storyEntry'],
      ),
    ).toEqual(['c3', 'c2', 'c1']);
    await expect(trigger.querySelector('[data-icon="expand"]')).not.toBeNull();
  },
};
export const FailureSplits: Story = {
  render: () => (
    <RunExample
      rows={[7, 6, 5, 4, 3, 2, 1].map((n) =>
        activityRow(n, n === 4 ? { result: 'failed', resultSource: 'flag' } : {}),
      )}
    />
  ),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getAllByRole('button', { name: /3 checks/ })).toHaveLength(2);
    const failed = canvas.getByLabelText('Failed, as the tool reported');
    await expect(failed).toBeVisible();
    await expect(failed.closest('[data-check-run]')).toBeNull();
    await expect(canvas.getByText('check 4')).toBeVisible();
  },
};
const narrowRow = {
  ...activityRow(1, { earlierFailed: true, beforeLastChange: true }, ['later', 'cited']),
  turn: true,
};
export const NarrowHead: Story = {
  parameters: { viewport: { defaultViewport: 'mobile1' } },
  globals: { viewport: { value: 'mobile1', isRotated: false } },
  render: () => (
    <TooltipProvider>
      <div style={{ width: 280, maxWidth: '100%' }}>
        <ActivityHead row={narrowRow} />
        <p className="next-cockpit-work-summary">The command stays in the body.</p>
      </div>
    </TooltipProvider>
  ),
  play: async ({ canvasElement }) => {
    const head = canvasElement.querySelector('.next-cockpit-work-head') as HTMLElement;
    const actor = head.querySelector('.next-cockpit-work-actor') as HTMLElement;
    const cluster = head.querySelector('[data-activity-head-right]') as HTMLElement;
    const at = head.querySelector('.next-cockpit-work-at') as HTMLElement;
    await expect(cluster.getBoundingClientRect().top).toBeGreaterThanOrEqual(
      actor.getBoundingClientRect().bottom,
    );
    await expect(at.getBoundingClientRect().right).toBeLessThanOrEqual(
      head.getBoundingClientRect().right + 1,
    );
    await expect(cluster.lastElementChild).toBe(at);
    await expect(within(head).getByLabelText('from the last turn')).toHaveTextContent('Last turn');
    await expect(within(head).getByText('Cited')).toBeVisible();
    await expect(within(canvasElement).getByText('The command stays in the body.')).toBeVisible();
  },
};

/* The list as Full activity draws it: in number order, so a check sits under the message whose number it carries
   even when it last ran later; the last turn said once, on its newest row, with the numbers it spans; and an
   agent's markdown emphasis drawn as the words it marks. */
const row = (n: string, at: number, turn: boolean, summary = `entry ${n}`): WorkRow => ({
  ...activityRow(at, { id: `e${n}`, summary }),
  n,
  turn,
});
const listed = [
  row('2', 1, false),
  row('3', 2, true, 'The risk is **High** until billing is reverted.'),
  row('2.1', 3, true),
  row('4', 4, true),
];
export const NumberOrderAndOneLastTurn: Story = {
  render: () => {
    const ordered = rowsByNumber(listed);
    const lead = lastTurnLead(ordered);
    return (
      <TooltipProvider delay={0}>
        <div role="list">
          {[...ordered].reverse().map((item) => (
            <div key={item.entry.id} data-story-entry={item.n} role="listitem">
              <ActivityHead row={item} turnRange={lead?.id === item.entry.id ? lead.range : null} />
              <p data-story-summary>{plainEmphasis(item.entry.summary)}</p>
            </div>
          ))}
        </div>
      </TooltipProvider>
    );
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const rows = [...canvasElement.querySelectorAll<HTMLElement>('[data-story-entry]')];
    await expect(rows.map((node) => node.dataset['storyEntry'])).toEqual(['4', '3', '2.1', '2']);
    const turns = canvas.getAllByLabelText(/^from the last turn/);
    await expect(turns).toHaveLength(1);
    await expect(turns[0]).toHaveTextContent('Last turn: #2.1 to #4');
    await expect(turns[0]?.closest('[data-story-entry]')).toBe(rows[0]);
    await userEvent.hover(turns[0] as HTMLElement);
    await expect(
      await within(canvasElement.ownerDocument.body).findByRole('tooltip'),
    ).toHaveTextContent('from the last turn, #2.1 to #4');
    await expect(canvas.getByText('The risk is High until billing is reverted.')).toBeVisible();
    await expect(canvasElement).not.toHaveTextContent('**');
  },
};
