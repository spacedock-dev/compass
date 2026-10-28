import type { Meta, StoryObj } from '@storybook/react-vite';
import { expect, userEvent, waitFor, within } from 'storybook/test';
import {
  analysisRow,
  DEPARTURE_READING,
  DriftScenario,
  fact,
  failedCheck,
  routeOf,
  type Scenario,
} from './drift.scenario';

/* What the Analyze press read of the bound pull request's CI checks from GitHub, and the page's switch for the
   read. The note says where the facts came from, when, and what they settle, from the stored record's closed
   tokens and counts alone: nothing the CLI printed reaches the card. The switch is the page's half of the
   turn-off, and `--no-ci-read` holds it off where the page cannot lift it. */

const meta = {
  title: 'Drift/Pull request CI read',
  component: DriftScenario,
} satisfies Meta<typeof DriftScenario>;
export default meta;
type Story = StoryObj<typeof meta>;

const scenario = (value: Scenario): Pick<Story, 'args'> => ({ args: { scenario: value } });

const HEAD = 'a'.repeat(40);
const OTHER = 'b'.repeat(40);
const PERSON = fact('u1', 200, { type: 'user_message', by: 'person:me', summary: 'Fix CI' });
const FACTS = [PERSON, failedCheck('c1', 500)];
const HIGH = { analysis_levels: [analysisRow('claude')] };

const record = (over: Record<string, unknown> = {}) => ({
  read_at: 1_000,
  error: '',
  source: 'goal',
  repository: 'acme/widgets',
  number: 12,
  head: HEAD,
  session_head: HEAD,
  head_matches: true,
  required_only: false,
  not_counted: 0,
  counts: { pass: 2, fail: 0, pending: 0, skipping: 1, cancel: 0 },
  caution: false,
  checks: [
    { name: 'lint', bucket: 'pass', completed_at: 900 },
    { name: 'unit-tests', bucket: 'pass', completed_at: 950 },
    { name: 'docs-preview', bucket: 'skipping', completed_at: null },
  ],
  ...over,
});

const read = (ci: Record<string, unknown>): Pick<Story, 'args'> =>
  scenario({
    facts: FACTS,
    work: HIGH,
    session: {
      annotation_assessment: { ...DEPARTURE_READING, ci },
      annotation_reading_count: 1,
    },
  });

const note = async (canvasElement: HTMLElement): Promise<HTMLElement> =>
  waitFor(() => {
    const node = canvasElement.querySelector<HTMLElement>('[data-next-ci-read]');
    if (!node) throw new Error('no CI note');
    return node;
  });

export const GreenOnTheSessionsCommit: Story = {
  ...read(record()),
  play: async ({ canvasElement }) => {
    const node = await note(canvasElement);
    await expect(node).toHaveAttribute('data-next-ci-read-state', 'settles');
    // Where it came from, when, which pull request, and the counts, skipped ones named apart.
    await expect(node).toHaveTextContent(
      /Pull request checks: Read from GitHub at (\d{4}-\d{2}-\d{2} )?\d{1,2}:\d{2}: acme\/widgets#12, 2 passed, 1 skipped\./,
    );
    await expect(node).toHaveTextContent(
      'Every check that counts passed on this session’s commit.',
    );
  },
};

/* A line the model cites the checks for holds on this page too: the cited checks resolve beside the session's
   own entries, so a green pull request on the session's commit reads as consistent and not as "Can't tell". */
const citing = (ci: Record<string, unknown>): Pick<Story, 'args'> =>
  scenario({
    facts: FACTS,
    session: {
      annotation_assessment: {
        ...DEPARTURE_READING,
        ci,
        criteria: {
          goal: {
            result: 'consistent with the evidence read',
            cites: ['ci:12:0', 'ci:12:1'],
            detail: '',
            clause: 'Ship the queue',
          },
          line_1: {
            result: 'consistent with the evidence read',
            cites: ['ci:12:1'],
            detail: '',
            clause: 'Tests pass',
          },
        },
      },
      annotation_reading_count: 1,
    },
  });

export const GreenChecksCarryAConsistentLine: Story = {
  ...citing(record()),
  play: async ({ canvasElement }) => {
    await note(canvasElement);
    const card = await within(canvasElement).findByRole('region', { name: 'Drift' });
    await waitFor(() => expect(card).toHaveTextContent('GitHub check'));
    await expect(card).not.toHaveTextContent('Can’t tell');
    await expect(card).not.toHaveTextContent("Can't tell");
  },
};

/* The same answer for a reader on GitLab: the card names the provider and the merge request by its own
   number sign, and a cited job resolves as a GitLab job. */
const GITLAB = 'gitlab.example.com/acme/widgets';

export const GreenOnAGitlabMergeRequest: Story = {
  ...citing(record({ repository: GITLAB })),
  play: async ({ canvasElement }) => {
    const node = await note(canvasElement);
    await expect(node).toHaveAttribute('data-next-ci-read-state', 'settles');
    await expect(node).toHaveTextContent(
      /Read from GitLab at (\d{4}-\d{2}-\d{2} )?\d{1,2}:\d{2}: gitlab\.example\.com\/acme\/widgets!12, 2 passed, 1 skipped\./,
    );
    const card = await within(canvasElement).findByRole('region', { name: 'Drift' });
    await waitFor(() => expect(card).toHaveTextContent('GitLab job'));
    await expect(card).not.toHaveTextContent('Can’t tell');
    await expect(card).not.toHaveTextContent("Can't tell");
  },
};

export const ChecksOnAMovedGitlabHeadNameTheMergeRequest: Story = {
  ...citing(record({ repository: GITLAB, head: OTHER, head_matches: false })),
  play: async ({ canvasElement }) => {
    const node = await note(canvasElement);
    await expect(node).toHaveAttribute('data-next-ci-read-state', 'unsettled');
    await expect(node).toHaveTextContent(
      'The merge request head is not this session’s commit, so they settle nothing.',
    );
    await expect(node).not.toHaveTextContent('pull request');
  },
};

export const AGitlabHostGlabDoesNotNameSaysSo: Story = {
  ...read(
    record({
      repository: GITLAB,
      error: 'host-not-configured',
      head: '',
      head_matches: false,
      counts: { pass: 0, fail: 0, pending: 0, skipping: 0, cancel: 0 },
      checks: [],
    }),
  ),
  play: async ({ canvasElement }) => {
    const node = await note(canvasElement);
    await expect(node).toHaveAttribute('data-next-ci-read-state', 'failed');
    await expect(node).toHaveTextContent(
      'Merge request checks were not read from GitLab: glab’s own configuration does not name that GitLab host.',
    );
  },
};

export const ChecksOnAMovedHeadCannotCarryALine: Story = {
  ...citing(record({ head: OTHER, head_matches: false })),
  play: async ({ canvasElement }) => {
    await note(canvasElement);
    const card = await within(canvasElement).findByRole('region', { name: 'Drift' });
    await waitFor(() => expect(card).toHaveTextContent("Can't tell"));
  },
};

export const StillRunningSettlesNothing: Story = {
  ...read(record({ counts: { pass: 1, fail: 0, pending: 1, skipping: 0, cancel: 0 } })),
  play: async ({ canvasElement }) => {
    const node = await note(canvasElement);
    await expect(node).toHaveAttribute('data-next-ci-read-state', 'unsettled');
    await expect(node).toHaveTextContent('1 passed, 1 still running');
    await expect(node).toHaveTextContent('Checks are still running, so they settle nothing.');
  },
};

export const AHeadPastTheSessionsCommitSettlesNothing: Story = {
  ...read(record({ head: OTHER, head_matches: false })),
  play: async ({ canvasElement }) => {
    const node = await note(canvasElement);
    await expect(node).toHaveAttribute('data-next-ci-read-state', 'unsettled');
    await expect(node).toHaveTextContent(
      'The pull request head is not this session’s commit, so they settle nothing.',
    );
  },
};

export const AnEditedWorkflowCarriesACaution: Story = {
  ...read(record({ caution: true })),
  play: async ({ canvasElement }) => {
    const node = await note(canvasElement);
    // Still settles, with the caution beside it.
    await expect(node).toHaveAttribute('data-next-ci-read-state', 'settles');
    await expect(node).toHaveTextContent('This session changed the CI configuration.');
  },
};

export const GhSignedOutSaysSoBesideTheReading: Story = {
  ...read(
    record({
      error: 'gh-signed-out',
      head: '',
      head_matches: false,
      counts: { pass: 0, fail: 0, pending: 0, skipping: 0, cancel: 0 },
      checks: [],
    }),
  ),
  play: async ({ canvasElement }) => {
    const node = await note(canvasElement);
    await expect(node).toHaveAttribute('data-next-ci-read-state', 'failed');
    await expect(node).toHaveTextContent(
      'Pull request checks were not read from GitHub: gh is not signed in, so run gh auth login to let Compass read them.',
    );
  },
};

export const NoSessionFolderSaysWhyNothingWasRead: Story = {
  ...read(
    record({
      error: 'no-session-folder',
      head: '',
      session_head: '',
      head_matches: false,
      counts: { pass: 0, fail: 0, pending: 0, skipping: 0, cancel: 0 },
      checks: [],
    }),
  ),
  play: async ({ canvasElement }) => {
    const node = await note(canvasElement);
    await expect(node).toHaveAttribute('data-next-ci-read-state', 'failed');
    await expect(node).toHaveTextContent(
      'Pull request checks were not read from GitHub: no folder is known for this session, so the pull request’s commit could not be matched to it.',
    );
  },
};

export const NoReadableCommitSaysWhyNothingWasRead: Story = {
  ...read(
    record({
      error: 'no-session-commit',
      head: '',
      session_head: '',
      head_matches: false,
      counts: { pass: 0, fail: 0, pending: 0, skipping: 0, cancel: 0 },
      checks: [],
    }),
  ),
  play: async ({ canvasElement }) => {
    const node = await note(canvasElement);
    await expect(node).toHaveAttribute('data-next-ci-read-state', 'failed');
    await expect(node).toHaveTextContent(
      'Pull request checks were not read from GitHub: the commit this session is on could not be read (git is off or the folder is not a repository), so the pull request’s commit could not be matched to it.',
    );
  },
};

export const RequiredOnlySaysHowManyChecksItLeftOut: Story = {
  ...read(
    record({
      required_only: true,
      not_counted: 2,
      counts: { pass: 1, fail: 0, pending: 0, skipping: 0, cancel: 0 },
      checks: [{ name: 'lint', bucket: 'pass', completed_at: 900 }],
    }),
  ),
  play: async ({ canvasElement }) => {
    const node = await note(canvasElement);
    await expect(node).toHaveTextContent('Only the checks GitHub requires are counted.');
    await expect(node).toHaveTextContent('2 non-required checks not counted.');
  },
};

export const NoNonRequiredChecksLeftOutSaysNothingOfThem: Story = {
  ...read(
    record({
      required_only: true,
      not_counted: 0,
      counts: { pass: 1, fail: 0, pending: 0, skipping: 0, cancel: 0 },
      checks: [{ name: 'lint', bucket: 'pass', completed_at: 900 }],
    }),
  ),
  play: async ({ canvasElement }) => {
    const node = await note(canvasElement);
    await expect(node).toHaveTextContent('Only the checks GitHub requires are counted.');
    await expect(node).not.toHaveTextContent('not counted');
  },
};

export const NoReadNoNote: Story = {
  ...scenario({
    facts: FACTS,
    work: HIGH,
    session: {
      annotation_assessment: DEPARTURE_READING,
      annotation_reading_count: 1,
    },
  }),
  play: async ({ canvasElement }) => {
    await waitFor(() =>
      expect(canvasElement.querySelector('[data-next-drift-verdict]')).not.toBeNull(),
    );
    await expect(canvasElement.querySelector('[data-next-ci-read]')).toBeNull();
  },
};

const SWITCH = '[data-next-ci-switch]';

async function opened(canvasElement: HTMLElement): Promise<HTMLElement> {
  const card = await within(canvasElement).findByRole('region', { name: 'Drift' });
  await userEvent.click(await within(card).findByRole('button', { name: /^What is sent/ }));
  return within(document.body).findByRole('dialog');
}

const ROUTE = routeOf('claude', {
  provider: 'claude',
  label: 'Claude Code',
  reason: 'own-harness',
  note: "This session's own harness reads it.",
  fallback: false,
});

export const TheSwitchTurnsTheReadOffAndBackOn: Story = {
  ...scenario({
    facts: FACTS,
    route: ROUTE,
    ciPosts: [],
  }),
  play: async ({ canvasElement, args }) => {
    const dialog = await opened(canvasElement);
    const posts = args.scenario.ciPosts ?? [];
    const node = await waitFor(() => {
      const found = dialog.querySelector<HTMLElement>(SWITCH);
      if (!found) throw new Error('no switch');
      return found;
    });
    await expect(node).toHaveAttribute('data-next-ci-switch', 'on');
    await expect(node).toHaveTextContent(
      'Pull request checks are read from GitHub or GitLab with your gh or glab login when you press Analyze.',
    );
    await userEvent.click(
      within(node).getByRole('button', { name: 'Turn off the pull request read' }),
    );
    // Saved on the server and read back from the board: the sentence follows the answer, not the press.
    await waitFor(() =>
      expect(dialog.querySelector(SWITCH)).toHaveAttribute('data-next-ci-switch', 'off'),
    );
    await expect(posts).toEqual([{ ci_read: 'off', press: true, observer_model: 1 }]);
    await expect(dialog.querySelector(SWITCH)).toHaveTextContent(
      'Pull request checks are not read from GitHub or GitLab.',
    );
    await userEvent.click(
      within(dialog.querySelector<HTMLElement>(SWITCH) as HTMLElement).getByRole('button', {
        name: 'Turn on the pull request read',
      }),
    );
    await waitFor(() =>
      expect(dialog.querySelector(SWITCH)).toHaveAttribute('data-next-ci-switch', 'on'),
    );
    await expect(posts).toHaveLength(2);
  },
};

export const TheFlagHoldsTheReadOffAndOffersNoSwitch: Story = {
  ...scenario({
    facts: FACTS,
    route: { ...ROUTE, ci_read: 'flag-off' },
    ciPosts: [],
  }),
  play: async ({ canvasElement }) => {
    const dialog = await opened(canvasElement);
    const node = await waitFor(() => {
      const found = dialog.querySelector<HTMLElement>(SWITCH);
      if (!found) throw new Error('no switch line');
      return found;
    });
    await expect(node).toHaveAttribute('data-next-ci-switch', 'flag-off');
    await expect(node).toHaveTextContent('for this run (--no-ci-read)');
    await expect(within(node).queryByRole('button')).toBeNull();
  },
};
