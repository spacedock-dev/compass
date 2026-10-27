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
  newestFirst,
  rowsByNumber,
  rowWords,
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
/* A command off the closed list reads with its exit status and what Compass does not know, never as a
   passed check, and a run of them is not folded into "N checks". A CI read keeps a check's words. */
export const CommandsKeepTheirLabel: Story = {
  render: () => (
    <RunExample
      rows={[
        activityRow(4, {
          subject: 'ci_command',
          result: 'passed',
          resultSource: 'flag',
          summary: 'gh pr checks 7',
        }),
        ...[3, 2, 1].map((n) =>
          activityRow(n, {
            subject: 'command',
            result: 'passed',
            resultSource: 'flag',
            summary: `make step${String(n)}`,
          }),
        ),
      ]}
    />
  ),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.queryByRole('button', { name: /checks/ })).toBeNull();
    await expect(canvasElement.querySelectorAll('[data-story-entry]')).toHaveLength(4);
    const labelled = canvas.getAllByLabelText('Exited 0; Compass does not know what it checks');
    await expect(labelled).toHaveLength(3);
    for (const mark of labelled) await expect(mark).toHaveTextContent('Exited 0');
    await expect(canvas.getAllByText('command')).toHaveLength(3);
    await expect(canvas.getByText('CI check')).toBeVisible();
    // Only the CI read says what a check says; no command says it passed.
    await expect(canvas.getAllByLabelText('Passed, as the tool reported')).toHaveLength(1);
    await expect(canvasElement.textContent).not.toMatch(/Passed, as the tool reported.*make step/);
  },
};

export const CommandWithAForcedStatusSaysSo: Story = {
  render: () => (
    <RunExample
      rows={[
        activityRow(1, {
          subject: 'command',
          result: 'not-recorded',
          resultSource: '',
          cannotFail: true,
          summary: 'make deploy || true',
        }),
      ]}
    />
  ),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(
      canvas.getByLabelText(
        'Ran, exit status not recorded: a later command forces the exit status to 0',
      ),
    ).toBeVisible();
    await expect(canvasElement.textContent).not.toMatch(/Exited 0/);
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

/* The list as Full activity draws it: newest first by message, so a check sits under the message whose number it
   carries even when it last ran later; the last turn said once, on its newest drawn row, with the numbers it spans;
   and an agent's markdown emphasis drawn as the words it marks, while a check command keeps its `**` globs. */
const row = (
  n: string,
  at: number,
  turn: boolean,
  summary = `entry ${n}`,
  type = 'agent_message',
): WorkRow => {
  const base = activityRow(at, { id: `e${n}`, summary, type });
  return {
    ...base,
    ...(type === 'tool_report' ? {} : { head: { actor: 'Agent', type: 'said' } }),
    n,
    turn,
  };
};
function ListExample({ rows }: { rows: readonly WorkRow[] }) {
  const [open, setOpen] = useState(false);
  const ordered = rowsByNumber(rows);
  const folded = foldRuns(newestFirst(ordered));
  const lead = lastTurnLead(ordered, folded);
  const draw = (item: WorkRow) => (
    <div key={item.entry.id} data-story-entry={item.n} role="listitem">
      <ActivityHead row={item} turnRange={lead?.id === item.entry.id ? lead.range : null} />
      <p data-story-summary>{rowWords(item.entry)}</p>
    </div>
  );
  return (
    <TooltipProvider delay={0}>
      <div role="list">
        {folded.map((item) =>
          item.kind === 'row' ? (
            draw(item.row)
          ) : (
            <CheckRun
              key={item.last.entry.id}
              run={item}
              turn={lead?.run === item.last.entry.id ? lead.range : null}
              open={open}
              onOpenChange={setOpen}
            >
              {item.rows.map(draw)}
            </CheckRun>
          ),
        )}
      </div>
    </TooltipProvider>
  );
}
const listed = [
  row('2', 1, false),
  row('3', 2, true, 'The risk is **High** until billing is reverted.'),
  row('2.1', 3, true, 'ls src/**/lib/**', 'tool_report'),
  row('4', 4, true),
];
export const NumberOrderAndOneLastTurn: Story = {
  render: () => <ListExample rows={listed} />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const rows = [...canvasElement.querySelectorAll<HTMLElement>('[data-story-entry]')];
    // Newest message first, and a check under the message whose number it carries.
    await expect(rows.map((node) => node.dataset['storyEntry'])).toEqual(['4', '3', '2', '2.1']);
    const turns = canvas.getAllByLabelText(/^from the last turn/);
    await expect(turns).toHaveLength(1);
    await expect(turns[0]).toHaveTextContent('Last turn: #2.1 to #4');
    await expect(turns[0]?.closest('[data-story-entry]')).toBe(rows[0]);
    await userEvent.hover(turns[0] as HTMLElement);
    await expect(
      await within(canvasElement.ownerDocument.body).findByRole('tooltip'),
    ).toHaveTextContent('from the last turn, #2.1 to #4');
    await expect(canvas.getByText('The risk is High until billing is reverted.')).toBeVisible();
    // A check command is literal source text: its globs are not emphasis.
    await expect(canvas.getByText('ls src/**/lib/**')).toBeVisible();
  },
};

/* A turn whose newest rows are passing checks that fold: the label is said on a row the reader can see, never only
   inside the closed run. */
const foldedTurn = [
  row('5', 1, false),
  row('6', 2, true, 'Running the suite now.'),
  row('6.1', 3, true, 'pytest tests/**/a.py tests/**/b.py', 'tool_report'),
  row('6.2', 4, true, 'pnpm test', 'tool_report'),
  row('6.3', 5, true, 'deny **/secrets/**', 'tool_report'),
];
export const LastTurnEndsInFoldedChecks: Story = {
  render: () => <ListExample rows={foldedTurn} />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const trigger = canvas.getByRole('button', { name: /3 checks/ });
    await expect(trigger).toHaveAttribute('aria-expanded', 'false');
    const turns = canvas.getAllByLabelText(/^from the last turn/);
    await expect(turns).toHaveLength(1);
    await expect(turns[0]).toBeVisible();
    await expect(turns[0]).toHaveTextContent('Last turn: #6 to #6.3');
    await expect(turns[0]?.closest('[data-story-entry]')?.getAttribute('data-story-entry')).toBe(
      '6',
    );
    await userEvent.click(trigger);
    await waitFor(() =>
      expect(canvas.getByText('pytest tests/**/a.py tests/**/b.py')).toBeVisible(),
    );
    await expect(canvas.getByText('deny **/secrets/**')).toBeVisible();
  },
};

/* Every row of the turn folds: the run's trigger says the turn, so the label is never shut inside it. */
export const WholeTurnFolded: Story = {
  render: () => (
    <ListExample
      rows={[
        row('7', 1, false),
        row('7.1', 2, true, 'pnpm lint', 'tool_report'),
        row('7.2', 3, true, 'pnpm test', 'tool_report'),
        row('7.3', 4, true, 'pnpm build', 'tool_report'),
      ]}
    />
  ),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const trigger = canvas.getByRole('button', { name: /3 checks/ });
    await expect(trigger).toHaveAttribute('aria-expanded', 'false');
    await expect(trigger).toHaveTextContent('Last turn: #7.1 to #7.3');
    await expect(trigger.querySelector('[data-check-run-turn]')).toBeVisible();
  },
};

const NOT_RECORDED_REASONS = [
  ['several_checks', 'several checks in one call'],
  ['directory_not_placeable', 'directory not placeable'],
  ['piped_beside_other_commands', 'output is piped beside other commands'],
] as const;
export const NotRecordedReasons: Story = {
  render: () => (
    <TooltipProvider delay={0}>
      <div role="list">
        {NOT_RECORDED_REASONS.map(([token, words], index) => (
          <div key={token} role="listitem" data-story-entry={token}>
            <ActivityHead row={activityRow(index + 1, { resultReason: token })} />
            <p>{`Ran, result not recorded: ${words}`}</p>
          </div>
        ))}
      </div>
    </TooltipProvider>
  ),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(
      canvas.getByLabelText('Ran, result not recorded: several checks in one call'),
    ).toHaveTextContent('No result: several checks in one call');
    await expect(
      canvas.getByLabelText('Ran, result not recorded: directory not placeable'),
    ).toHaveTextContent('No result: directory not placeable');
    await expect(
      canvas.getByLabelText('Ran, result not recorded: output is piped beside other commands'),
    ).toHaveTextContent('No result: output is piped beside other commands');
  },
};
