import type { Meta, StoryObj } from '@storybook/react-vite';
import { expect, userEvent, waitFor, within } from 'storybook/test';
import { DriftScenario, fact, passedCheck, type Scenario } from './drift.scenario';

/* The sentence "About this record" gives of what the whole scan of a session found: the check runs and their
   latest results, the files written, what was counted and not listed, and, where the session wrote the file a
   reader lists checks in, that none of the listed commands counted. Every figure is the scan's, never the listed
   rows'. Each story feeds one published scan and asserts the sentence it draws. */

const meta = {
  title: 'Drift/Check scan sentence',
  component: DriftScenario,
} satisfies Meta<typeof DriftScenario>;
export default meta;
type Story = StoryObj<typeof meta>;

const LISTING =
  'The session wrote the file where you list checks, so none of the commands you listed counted as checks.';

const codexScanned = (scan: Record<string, unknown>): Pick<Story, 'args'> => ({
  args: {
    scenario: {
      harness: 'codex',
      facts: [fact('u1', 200, { type: 'user_message', by: 'person:me' }, 'codex')],
      work: { tool_reports: [{ harness: 'codex', sid: 's1', ...scan }] },
    },
  },
});

const scanned = (scan: Record<string, unknown>): Pick<Story, 'args'> => {
  const value: Scenario = {
    facts: [passedCheck('c1', 500), fact('u1', 200, { type: 'user_message', by: 'person:me' })],
    work: { tool_reports: [{ harness: 'claude', sid: 's1', ...scan }] },
  };
  return { args: { scenario: value } };
};

const sentence = async (canvasElement: HTMLElement): Promise<HTMLElement> => {
  const canvas = within(canvasElement);
  const about = await canvas.findByRole('button', { name: /About this record/ }, { timeout: 8000 });
  if (about.getAttribute('aria-expanded') !== 'true') await userEvent.click(about);
  return waitFor(() => {
    const node = canvasElement.querySelector<HTMLElement>('.next-cockpit-work-checks');
    if (!node) throw new Error('no check scan sentence');
    return node;
  });
};

/* A Codex rollout written before codex-cli 0.149 records no exit status. Its scan publishes that alone, and the
   sentence says so, never "No check ran", which would be the schema speaking rather than the session. */
export const ACodexVersionWithNoExitStatusIsNotRead: Story = {
  ...codexScanned({ commands_unreadable: true }),
  play: async ({ canvasElement }) => {
    const node = await sentence(canvasElement);
    await expect(node).toHaveTextContent(
      'This Codex version records no exit status, so its commands are not read and no check is counted.',
    );
    await expect(node).not.toHaveTextContent('No check ran');
  },
};

export const NoCheckRan: Story = {
  ...scanned({}),
  play: async ({ canvasElement }) => {
    const node = await sentence(canvasElement);
    await expect(node).toHaveTextContent('No check ran in the part of the transcript read.');
    await expect(node).not.toHaveTextContent(LISTING);
  },
};

export const NoCheckRanAndTheListingWasWritten: Story = {
  ...scanned({ reader_checks_written: true }),
  play: async ({ canvasElement }) => {
    const node = await sentence(canvasElement);
    await expect(node).toHaveTextContent(
      `No check ran in the part of the transcript read. ${LISTING}`,
    );
  },
};

export const RunsAndTheirLatestResults: Story = {
  ...scanned({ check_runs: 3, distinct_checks: 2, failed: 1, not_recorded: 1, passed: 1 }),
  play: async ({ canvasElement }) => {
    const node = await sentence(canvasElement);
    await expect(node).toHaveTextContent(
      'From the part of the transcript read: 3 check runs across 2 distinct checks; latest runs: 1 failed, 1 with no recorded result, 1 passed.',
    );
    await expect(node).not.toHaveTextContent(LISTING);
  },
};

export const OneRunReadsInTheSingular: Story = {
  ...scanned({ check_runs: 1, distinct_checks: 1, failed: 0, not_recorded: 0, passed: 1 }),
  play: async ({ canvasElement }) => {
    await expect(await sentence(canvasElement)).toHaveTextContent(
      '1 check run across 1 distinct check; latest runs: 0 failed, 0 with no recorded result, 1 passed.',
    );
  },
};

export const FilesWrittenInAndOutsideTheWorkingDirectory: Story = {
  ...scanned({ written_paths: 2, outside_paths: 1 }),
  play: async ({ canvasElement }) => {
    const node = await sentence(canvasElement);
    await expect(node).toHaveTextContent('no check in the foreground');
    await expect(node).toHaveTextContent(
      '2 files written, 1 file written outside the working directory.',
    );
  },
};

export const PullRequestsAndSkillsAreSaidApart: Story = {
  ...scanned({ pull_requests: 1, skills_used: 2 }),
  play: async ({ canvasElement }) => {
    const node = await sentence(canvasElement);
    await expect(node).not.toHaveTextContent('No check ran');
    await expect(node).toHaveTextContent('1 pull request created, 2 skills used.');
  },
};

export const BackgroundAndOtherCommandsAreCountedNotListed: Story = {
  ...scanned({ background: 2, other_commands: 5 }),
  play: async ({ canvasElement }) => {
    await expect(await sentence(canvasElement)).toHaveTextContent(
      'Counted and not listed: 2 background launches, because a background run records no result; 5 other shell commands.',
    );
  },
};

export const FailuresAreListedFirstAndTheRestCounted: Story = {
  ...scanned({
    check_runs: 14,
    distinct_checks: 3,
    failed: 2,
    not_recorded: 0,
    passed: 1,
    more: 2,
  }),
  play: async ({ canvasElement }) => {
    await expect(await sentence(canvasElement)).toHaveTextContent(
      'Failures are listed first, and 2 more are counted and not listed.',
    );
  },
};

export const TheListingNoteComesAfterTheRest: Story = {
  ...scanned({
    check_runs: 1,
    distinct_checks: 1,
    failed: 0,
    not_recorded: 1,
    passed: 0,
    reader_checks_written: true,
  }),
  play: async ({ canvasElement }) => {
    const node = await sentence(canvasElement);
    await expect(node.textContent?.endsWith(LISTING)).toBe(true);
    await expect(node).toHaveTextContent('1 check run across 1 distinct check');
  },
};
