import type { Meta, StoryObj } from '@storybook/react-vite';
import { seeInContext } from './citation';
import { expect, userEvent, waitFor, within } from 'storybook/test';
import {
  CHECK_DOES_NOT_SHOW_IT,
  READ_NEVER,
  READ_SUMMARY,
  READING_DEFINITION,
  RESULT_CANT_TELL,
  RESULT_MARKED,
  RESULT_NOT_ACCURATE,
  RESULT_NOTHING_SHOWS_REASON,
  RESULT_UNMARK,
  TELLS_THE_PERSON,
  UNKNOWN_KEY,
} from '../src/drift/sentences';
import { neverDone } from './drift.checks';
import { routeFor } from './drift.reasons';
import {
  DEPARTURE_READING,
  DriftScenario,
  failedCheck,
  fact,
  passedCheck,
  written,
  type Scenario,
} from './drift.scenario';

/* The Drift card's result, one story per state it can draw: each departure as its own card (its constraint, the
   constraint's own words, What as the cited entries by number and Why as the stored detail), then one quiet row
   per remaining line, Steer back by its unchanged rules, and the quiet footer. The table of these states, with
   the rendering before and after, is in the pull request. Every story asserts what a reader can check: which
   constraint a card is about, that each number names a row in Full activity and opens on it, whose words each
   sentence is, and that nothing says the work was done. */

const meta = {
  title: 'Drift/Departure cards and quiet rows',
  component: DriftScenario,
} satisfies Meta<typeof DriftScenario>;
export default meta;
type Story = StoryObj<typeof meta>;

const scenario = (value: Scenario): Pick<Story, 'args'> => ({ args: { scenario: value } });

/* The record every story reads from, by role: the person's message, a failing and a passing check, the agent's
   claim, and an agent entry that is not a message. */
const PERSON = fact('u1', 200, { type: 'user_message', by: 'person:me', summary: 'Ship it' });
const FAILED = failedCheck('c1', 500);
const PASSED = passedCheck('c2', 600);
const CLAIM = fact('m1', 650, {
  type: 'agent_message',
  by: 'agent',
  summary: 'All green locally: the tests pass.',
});
const NOTE = fact('n1', 700, { type: 'task_update', by: 'agent', summary: 'Queue worker started' });
const STAMP = 'claude-sonnet-5-5 · read at 09:38';

const reading = (criteria: Record<string, unknown>, extra: Record<string, unknown> = {}) => ({
  ...DEPARTURE_READING,
  stamp: STAMP,
  criteria,
  ...extra,
});
const stored = (assessment: Record<string, unknown>, extra: Record<string, unknown> = {}) => ({
  annotation_assessment: assessment,
  annotation_reading_count: 1,
  ...extra,
});

const GOAL_DEPARTS = {
  result: 'departure',
  cites: ['c1'],
  detail: 'It stopped running the tests.',
  clause: 'Ship the queue',
};
const GOAL_CONSISTENT = {
  result: 'consistent with the evidence read',
  cites: ['c2'],
  detail: '',
  clause: 'Ship the queue',
};
const LINE_CONSISTENT = {
  result: 'consistent with the evidence read',
  cites: ['c2'],
  detail: '',
  clause: 'Tests pass',
};

async function card(canvasElement: HTMLElement): Promise<HTMLElement> {
  return within(canvasElement).findByRole('region', { name: 'Drift' });
}

async function result(root: HTMLElement): Promise<HTMLElement> {
  return waitFor(() => {
    const node = root.querySelector<HTMLElement>('[data-next-result]');
    expect(node).not.toBeNull();
    return node as HTMLElement;
  });
}

/* The card's one answer, a sentence under its heading. */
async function verdictOf(root: HTMLElement): Promise<HTMLElement> {
  return waitFor(() => {
    const node = root.querySelector<HTMLElement>('[data-next-drift-verdict]');
    expect(node).not.toBeNull();
    return node as HTMLElement;
  });
}

const departures = (root: HTMLElement) => [
  ...root.querySelectorAll<HTMLElement>('[data-next-departure]'),
];
const quietRow = (root: HTMLElement, key: string) =>
  root.querySelector<HTMLElement>(`[data-next-result-row="${key}"]`) as HTMLElement;
const chips = (root: HTMLElement) => [
  ...root.querySelectorAll<HTMLElement>('[data-next-cite]:not([data-next-cite=""])'),
];
const primaries = (root: HTMLElement) => [
  ...root.querySelectorAll<HTMLElement>('[data-variant="primary"]'),
];

/* Each number on a finding is the activity list's own: a button named for the number, the constraint and the
   reader's words, with the kind of entry Compass names beside it (on a departure card, the entry's own words,
   attributed), and a row in Full activity that carries the same number. */
async function citesResolvably(root: HTMLElement, constraint: string, clause: string) {
  const found = chips(root);
  await expect(found.length).toBeGreaterThan(0);
  for (const chip of found) {
    const cite = chip.textContent ?? '';
    await expect(cite).toMatch(/^\[\d+(\.\d+)?\]$/);
    const number = `#${cite.slice(1, -1)}`;
    await expect(chip).toHaveAccessibleName(
      `Show ${number} in Full activity for ${clause ? `${constraint}: ${clause}` : constraint}`,
    );
    await expect(chip.previousSibling?.textContent).toMatch(
      /^(failed check|passed check|File write|Agent message|Your message|Recorded entry|Agent said: “.+”|(At (\d\d:\d\d|a time not recorded) (the agent changed .+\.|a check (failed|ran)(: .+\.|\.)|the agent said (“.+”|something)\.|you said “.+”\.|[a-z ]+ was recorded\.))|\[\d+(\.\d+)?\]|You said: “.+”|(Failed|Passed|Recorded) check: .+|File write: .+)$/,
    );
    const row = document.querySelector<HTMLElement>(
      `[data-next-entry-id="${CSS.escape(chip.dataset['nextCite'] ?? '')}"]`,
    );
    await expect(row).not.toBeNull();
    await expect(row?.textContent).toContain(number);
  }
}

/* A departure card names its constraint, quotes the reader's own words as its headline, and gives Why as the
   stored detail under its label, so no sentence on it is a model's but the one it is attributed to. */
async function departureCard(
  node: HTMLElement,
  label: string,
  clause: string,
  detail: string,
  constraint: string,
) {
  await expect(node).toHaveAttribute('data-next-result-state', 'departs');
  await expect(node.querySelector('[data-next-departure-label]')).toHaveTextContent(
    `Departure · ${label}`,
  );
  /* The headline is what happened, derived from the cited entry (`departureTitle`), and never the constraint's
     own sentence, which the label above it already names. */
  const heading = within(node).getByRole('heading', { level: 4 });
  await expect(heading.textContent).toMatch(
    /^(It changed .+ against .+|(A check failed|A check ran)( at \d\d:\d\d)? against .+|(What the agent said|Your own words|Something in the record)( at \d\d:\d\d)? depart(s)? from .+)$/,
  );
  await expect(heading.textContent).not.toBe(clause);
  await expect(node).toHaveAccessibleName(heading.textContent ?? '');
  const why = node.querySelector('[data-next-departure-why]') as HTMLElement;
  await expect(why.firstElementChild).toHaveTextContent('Why Compass reads this as drift');
  await expect(why.lastElementChild).toHaveTextContent(detail);
  const what = node.querySelector('[data-next-departure-what]') as HTMLElement;
  await expect(what.firstElementChild).toHaveTextContent('What');
  await citesResolvably(what, constraint, clause);
  /* Said once, in Evidence: "Departs; evidence #n" beside the label and What said it a third time. */
  await expect(node.querySelector('[data-next-departure-status]')).toBeNull();
  await expect(
    node.querySelector('[data-next-departure-what] [data-next-cite]')?.previousSibling
      ?.textContent ?? '',
  ).not.toMatch(/^Departs/);
  await expect(
    [...node.querySelectorAll('.ctl-disclosure')].map((part) => part.textContent).join(' '),
  ).toMatch(/Departs; evidence \[\d+\]/);
}

async function stamp(root: HTMLElement) {
  await waitFor(() =>
    expect(root.querySelector('[data-next-drift-stamp]')).toHaveTextContent(
      /^claude-sonnet-5-5 · Analysis last run \d\d:\d\d$/,
    ),
  );
}

/* The reason for Can't tell is in view under the line, in the design's form `Can't tell · <line>` then why (the
   redesign walk, 2026-10-21, which replaces the 2026-10-14 ruling that kept it inside Evidence). It is said once:
   opening Evidence does not repeat it. */
async function reasonInView(row: HTMLElement, sentence: string | RegExp) {
  const reason = row.querySelector<HTMLElement>('[data-next-reason]') as HTMLElement;
  await expect(reason).not.toBeNull();
  await expect(reason).toBeVisible();
  if (typeof sentence === 'string') await expect(reason.textContent).toBe(sentence);
  else await expect(reason.textContent).toMatch(sentence);
  await expect(reason.textContent).not.toContain('what was read does not settle this');
  await userEvent.click(within(row).getByRole('button', { name: 'Evidence' }));
  await expect(
    [...row.querySelectorAll('.next-cockpit-reading-why')].filter(
      (node) => node.textContent === reason.textContent,
    ),
  ).toHaveLength(1);
}

async function noRetiredResultWords(root: HTMLElement) {
  await expect(root.textContent).not.toContain('Model assessment');
  await expect(root.textContent).not.toContain('Show cited entries');
}

/* The acceptance case: two departures, a line it can't tell and an unbacked claim. Two cards, then a divider and
   two quiet rows, then Steer back as the one primary. */
export const TwoDeparturesACantTellAndAClaim: Story = {
  ...scenario({
    session: {
      annotation_line_1: 'Tests pass',
      annotation_line_2: 'The docs say how to run it',
      ...stored(
        reading({
          goal: GOAL_DEPARTS,
          line_1: {
            result: 'departure',
            cites: ['c1'],
            detail: 'pytest failed after your words.',
            clause: 'Tests pass',
          },
          line_2: {
            result: 'not verifiable from available evidence',
            cites: [],
            detail: '',
            clause: 'The docs say how to run it',
            why: 'check-does-not-show-it',
          },
          claims: {
            result: 'not shown by the record',
            cites: ['m1'],
            detail: 'Nothing on record shows the tests passing.',
            clause: '',
          },
        }),
      ),
    },
    facts: [PERSON, FAILED, CLAIM],
  }),
  play: async ({ canvasElement }) => {
    const drift = await card(canvasElement);
    const shown = await result(drift);
    await stamp(drift);
    // The answer is the verdict sentence under the card's heading, said once.
    await expect(await verdictOf(drift)).toHaveTextContent('2 departures');
    await expect(drift.querySelector('[data-next-result-heading]')).toBeNull();
    const cards = departures(shown);
    await expect(cards.map((node) => node.dataset['nextDeparture'])).toEqual(['goal', 'line_1']);
    await departureCard(
      cards[0] as HTMLElement,
      'Goal',
      'Ship the queue',
      'It stopped running the tests.',
      'Goal',
    );
    await departureCard(
      cards[1] as HTMLElement,
      'Expected outcome 1',
      'Tests pass',
      'pytest failed after your words.',
      'Expected outcome line 1',
    );
    const quiet = shown.querySelector('[data-next-result-quiet]') as HTMLElement;
    // The divider stands between the cards and the quiet rows.
    await expect(getComputedStyle(quiet).borderTopStyle).toBe('solid');
    const cantTell = quietRow(quiet, 'line_2');
    await expect(cantTell).toHaveAttribute('data-next-result-state', 'cant-tell');
    await expect(cantTell).toHaveTextContent(`${RESULT_CANT_TELL} · “The docs say how to run it”`);
    await reasonInView(cantTell, CHECK_DOES_NOT_SHOW_IT);
    const claim = quietRow(quiet, 'claims');
    await expect(claim).toHaveAttribute('data-next-result-state', 'unshown');
    // The claim is quoted, as the design has it, and the row says where the agent made it.
    await expect(claim).toHaveTextContent(
      /^What the agent claimed · “All green locally: the tests pass” is not shown by the record/,
    );
    await citesResolvably(claim, 'What the agent claimed', '');
    // The quiet rows come after every card.
    await expect(
      (cards[1] as HTMLElement).compareDocumentPosition(quiet) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    const steer = await within(drift).findByRole('button', { name: 'Steer back' });
    await expect(primaries(canvasElement)).toEqual([steer]);
    await expect(
      quiet.compareDocumentPosition(steer) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    await neverDone(shown);
    await noRetiredResultWords(shown);
  },
};

/* The stored reading keeps a `detail` and no headline, so a card's title is derived from the entry it cites. Two
   departures that cite two agent messages used to both read "What the agent said departs from this" (walk of the
   sample session, 2026-10-21); each now says when, and which constraint it departs from. */
export const TwoDeparturesOnTwoMessagesAreTitledApart: Story = {
  ...scenario({
    session: {
      annotation_line_1: 'Tests pass',
      ...stored(
        reading({
          goal: { ...GOAL_DEPARTS, cites: ['m1'] },
          line_1: {
            result: 'departure',
            cites: ['m2'],
            detail: 'It said nothing about the lint.',
            clause: 'Tests pass',
          },
        }),
      ),
    },
    facts: [
      PERSON,
      CLAIM,
      fact('m2', 800, { type: 'agent_message', by: 'agent', summary: 'Lint is clean too.' }),
    ],
  }),
  play: async ({ canvasElement }) => {
    const shown = await result(await card(canvasElement));
    const titles = departures(shown).map(
      (node) => within(node).getByRole('heading', { level: 4 }).textContent,
    );
    await expect(titles).toHaveLength(2);
    await expect(new Set(titles).size).toBe(2);
    await expect(titles[0]).toMatch(/^What the agent said at \d\d:\d\d departs from the goal$/);
    await expect(titles[1]).toMatch(
      /^What the agent said at \d\d:\d\d departs from the expected outcome$/,
    );
  },
};

/* A number opens Full activity on that entry, not on the finding's first; Back to the finding returns to it. */
export const ANumberOpensFullActivityAtItsEntry: Story = {
  ...scenario({
    session: stored(
      reading({
        goal: { ...GOAL_DEPARTS, cites: ['c1', 'c3'] },
        line_1: LINE_CONSISTENT,
      }),
    ),
    facts: [PERSON, FAILED, failedCheck('c3', 550), PASSED],
  }),
  play: async ({ canvasElement }) => {
    const drift = await card(canvasElement);
    const shown = await result(drift);
    const goal = departures(shown)[0] as HTMLElement;
    await waitFor(() => expect(chips(goal)).toHaveLength(2));
    const second = chips(goal)[1] as HTMLElement;
    await seeInContext(second);
    const row = await waitFor(() => {
      const node = document.activeElement as HTMLElement;
      expect(node.dataset['nextEntryId']).toBe('c3');
      return node;
    });
    await expect(row).toHaveTextContent(`#${(second.textContent ?? '').slice(1, -1)}`);
    await expect(document.querySelectorAll('[data-next-cited]').length).toBe(2);
    await userEvent.click(within(row).getByRole('button', { name: 'Back to the finding' }));
    await waitFor(() => expect(document.activeElement).toBe(second));
  },
};

/* Not reached at this stop, beside a goal consistent with a check, as the tool reported it. No card, no divider,
   no Steer back. */
export const NotReachedAndConsistentWithACheck: Story = {
  ...scenario({
    session: stored(
      reading(
        {
          goal: GOAL_CONSISTENT,
          line_1: {
            result: 'not reached at this stop',
            cites: ['m1'],
            detail: 'The work stopped before the tests.',
            clause: 'Tests pass',
          },
        },
        { scope: 'last-turn' },
      ),
    ),
    facts: [PERSON, PASSED, CLAIM],
  }),
  play: async ({ canvasElement }) => {
    const drift = await card(canvasElement);
    const shown = await result(drift);
    await expect(await verdictOf(drift)).toHaveTextContent('Not reached at this stop.');
    await expect(departures(shown)).toHaveLength(0);
    const quiet = shown.querySelector('[data-next-result-quiet]') as HTMLElement;
    await expect(getComputedStyle(quiet).borderTopStyle).toBe('none');
    const goal = quietRow(quiet, 'goal');
    await expect(goal).toHaveAttribute('data-next-result-state', 'consistent');
    await expect(goal).toHaveTextContent(/^Consistent with \[\d+(\.\d+)?\] · “Ship the queue”/);
    await citesResolvably(goal, 'Goal', 'Ship the queue');
    const line = quietRow(quiet, 'line_1');
    await expect(line).toHaveAttribute('data-next-result-state', 'not-reached');
    await expect(line).toHaveTextContent('Not reached at this stop · “Tests pass”');
    // The tool's report is named as the tool's, in full, behind Evidence.
    await userEvent.click(within(goal).getByRole('button', { name: 'Evidence' }));
    await waitFor(() => expect(goal).toHaveTextContent('as the tool reported; not inspected'));
    await expect(within(drift).queryByRole('button', { name: 'Steer back' })).toBeNull();
    await neverDone(shown);
  },
};

/* Consistent with what the agent said: the agent's own words, never a check. */
export const ConsistentWithTheAgent: Story = {
  ...scenario({
    session: stored(
      reading({
        goal: { ...GOAL_CONSISTENT, cites: ['m1'] },
        line_1: LINE_CONSISTENT,
      }),
    ),
    facts: [PERSON, PASSED, CLAIM],
  }),
  play: async ({ canvasElement }) => {
    const shown = await result(await card(canvasElement));
    const goal = await waitFor(() => {
      const node = quietRow(shown, 'goal');
      expect(node).not.toBeNull();
      return node;
    });
    await expect(goal).toHaveTextContent(/^Consistent with what the agent said at \[\d+\]/);
    await citesResolvably(goal, 'Goal', 'Ship the queue');
    await expect(goal.textContent).not.toContain('All green locally');
    await userEvent.click(within(goal).getByRole('button', { name: 'Evidence' }));
    await waitFor(() => expect(goal).toHaveTextContent('; not a check'));
    await neverDone(shown);
  },
};

/* Consistent with what the session said: an agent entry that is not one of its messages. */
export const ConsistentWithTheSession: Story = {
  ...scenario({
    session: stored(
      reading({
        goal: { ...GOAL_CONSISTENT, cites: ['n1'] },
        line_1: LINE_CONSISTENT,
      }),
    ),
    facts: [PERSON, PASSED, NOTE],
  }),
  play: async ({ canvasElement }) => {
    const shown = await result(await card(canvasElement));
    const goal = await waitFor(() => {
      const node = quietRow(shown, 'goal');
      expect(node).not.toBeNull();
      return node;
    });
    await expect(goal).toHaveTextContent(
      /^Consistent with what the session said at (\[\d+(\.\d+)?\]|\d\d:\d\d)/,
    );
    await expect(goal.textContent).not.toContain('Queue worker started');
    await neverDone(shown);
  },
};

/* Can't tell, with the page's own reason, and nothing shown, where no reason was given. */
export const CantTellAndNothingShown: Story = {
  ...scenario({
    session: {
      annotation_line_2: 'The docs say how to run it',
      ...stored(
        reading({
          goal: GOAL_CONSISTENT,
          line_1: {
            result: 'not verifiable from available evidence',
            cites: [],
            detail: '',
            clause: 'Tests pass',
            why: 'check-does-not-show-it',
          },
          line_2: {
            result: 'not verifiable from available evidence',
            cites: [],
            detail: '',
            clause: 'The docs say how to run it',
          },
        }),
      ),
    },
    facts: [PERSON, PASSED],
  }),
  play: async ({ canvasElement }) => {
    const drift = await card(canvasElement);
    const shown = await result(drift);
    await expect(await verdictOf(drift)).toHaveTextContent(RESULT_CANT_TELL);
    await expect(departures(shown)).toHaveLength(0);
    const cantTell = quietRow(shown, 'line_1');
    await expect(cantTell).toHaveAttribute('data-next-result-state', 'cant-tell');
    await expect(cantTell).toHaveTextContent(`${RESULT_CANT_TELL} · “Tests pass”`);
    await reasonInView(cantTell, CHECK_DOES_NOT_SHOW_IT);
    const nothing = quietRow(shown, 'line_2');
    await expect(nothing).toHaveTextContent(`${RESULT_CANT_TELL} · “The docs say how to run it”`);
    await reasonInView(nothing, RESULT_NOTHING_SHOWS_REASON);
    await expect(chips(nothing)).toHaveLength(0);
    await neverDone(shown);
  },
};

/* A write the record holds, inside a folder the line rules out, settles the line: the producer stores it as a
   departure that rests on the written paths, and the page lets those paths carry it where it lets no other
   write. The card shows the departure beside the same list of written files that used to contradict "Can't
   tell". */
const FOLDER_LINE = 'No file under frontend/e2e is edited';
const WRITES = [
  written('w1', 520, 'frontend/e2e/support/state.ts'),
  written('w2', 530, 'frontend/e2e/a.spec.ts'),
];
const folderReading = (why: string) => ({
  annotation_line_1: FOLDER_LINE,
  ...stored(
    reading({
      goal: GOAL_CONSISTENT,
      line_1: {
        result: 'departure',
        cites: ['w1', 'w2'],
        detail: '2 files recorded as written under frontend/e2e, which this line rules out.',
        clause: FOLDER_LINE,
        why,
      },
    }),
  ),
});

export const ARecordedWriteSettlesALineThatRulesOutItsFolder: Story = {
  ...scenario({ session: folderReading('recorded-write'), facts: [PERSON, PASSED, ...WRITES] }),
  play: async ({ canvasElement }) => {
    const drift = await card(canvasElement);
    const shown = await result(drift);
    await expect(await verdictOf(drift)).toHaveTextContent('1 departure');
    const cards = departures(shown);
    await expect(cards.map((node) => node.dataset['nextDeparture'])).toEqual(['line_1']);
    await departureCard(
      cards[0] as HTMLElement,
      'Expected outcome',
      FOLDER_LINE,
      '2 files recorded as written under frontend/e2e, which this line rules out.',
      'Expected outcome line 1',
    );
    await expect(chips(cards[0] as HTMLElement)).toHaveLength(2);
    await neverDone(shown);
  },
};

/* The same two writes cited with no `recorded-write` token are a model's departure on a write alone, which
   carries no result: the page still withdraws it, so the token is what lets a write stand and nothing else. */
export const AModelsDepartureOnAWriteAloneIsStillWithdrawn: Story = {
  ...scenario({ session: folderReading(''), facts: [PERSON, PASSED, ...WRITES] }),
  play: async ({ canvasElement }) => {
    const drift = await card(canvasElement);
    const shown = await result(drift);
    await expect(departures(shown)).toHaveLength(0);
    const row = quietRow(shown, 'line_1');
    await expect(row).toHaveAttribute('data-next-result-state', 'cant-tell');
    await reasonInView(row, CHECK_DOES_NOT_SHOW_IT);
  },
};

/* Every line that reads Can't tell says why in the sentence under it, and no two say the same unless they rest
   on the same thing: a rule that withdrew it, the entries it read and found silent, or that nothing recorded
   speaks to it. The generic "what was read does not settle this" is gone. */
export const EveryCantTellLineSaysItsOwnReason: Story = {
  ...scenario({
    session: {
      annotation_line_1: 'The docs say how to run it',
      annotation_line_2: 'The agent reports the counts',
      annotation_line_3: 'The migration is reversible',
      annotation_line_4: 'The changelog names the fix',
      ...stored(
        reading({
          goal: GOAL_CONSISTENT,
          line_1: {
            result: 'not verifiable from available evidence',
            cites: [],
            detail: '',
            clause: 'The docs say how to run it',
            why: 'check-does-not-show-it',
          },
          line_2: {
            result: 'not verifiable from available evidence',
            cites: [],
            detail: '',
            clause: 'The agent reports the counts',
            why: 'tells-the-person',
          },
          line_3: {
            result: 'not verifiable from available evidence',
            cites: ['c2'],
            detail: '',
            clause: 'The migration is reversible',
          },
          line_4: {
            result: 'not verifiable from available evidence',
            cites: [],
            detail: '',
            clause: 'The changelog names the fix',
          },
        }),
      ),
    },
    facts: [PERSON, PASSED],
  }),
  play: async ({ canvasElement }) => {
    const shown = await result(await card(canvasElement));
    const rows = [
      ...shown.querySelectorAll<HTMLElement>('[data-next-result-state="cant-tell"]'),
    ].filter((node) => node.dataset['nextResultRow']?.startsWith('line_'));
    await expect(rows).toHaveLength(4);
    const reasons = rows.map(
      (node) => node.querySelector<HTMLElement>('[data-next-reason]')?.textContent ?? '',
    );
    for (const reason of reasons) {
      await expect(reason.length).toBeGreaterThan(0);
      await expect(reason).not.toContain('what was read does not settle this');
    }
    await expect(new Set(reasons).size).toBe(4);
    await expect(reasons[0]).toBe(CHECK_DOES_NOT_SHOW_IT);
    await expect(reasons[1]).toBe(TELLS_THE_PERSON);
    await expect(reasons[2]).toMatch(
      /^What it read, \[\d+(\.\d+)?\], neither shows nor contradicts this\.$/,
    );
    await expect(reasons[3]).toBe(RESULT_NOTHING_SHOWS_REASON);
    for (const node of rows) {
      await expect(node.textContent).toMatch(/^Can't tell · “/);
    }
    await neverDone(shown);
  },
};

/* The agent's claim, contradicted: the quiet row says where, gives the stored detail and cites both entries. */
export const ClaimContradicted: Story = {
  ...scenario({
    session: stored(
      reading({
        goal: GOAL_CONSISTENT,
        line_1: LINE_CONSISTENT,
        claims: {
          result: 'departure',
          cites: ['m1', 'c1'],
          detail: 'pytest failed after the agent said the tests pass.',
          clause: '',
        },
      }),
    ),
    facts: [PERSON, PASSED, CLAIM, failedCheck('c1', 700)],
  }),
  play: async ({ canvasElement }) => {
    const shown = await result(await card(canvasElement));
    const claim = await waitFor(() => {
      const node = quietRow(shown, 'claims');
      expect(node).not.toBeNull();
      return node;
    });
    await expect(claim).toHaveAttribute('data-next-result-state', 'departs');
    await expect(claim).toHaveTextContent(
      /^What the agent claimed · “All green locally: the tests pass” is contradicted at \[\d+(\.\d+)?\]/,
    );
    await expect(claim).toHaveTextContent('pytest failed after the agent said the tests pass.');
    await citesResolvably(claim, 'What the agent claimed', '');
    await expect(chips(claim)).toHaveLength(2);
    // A claim never departs from the intent: no card for it.
    await expect(departures(shown)).toHaveLength(0);
    await neverDone(shown);
  },
};

/* A contradicted claim whose stored detail is empty or only whitespace still says no explanation was retained,
   and still lists each cited entry's own record under Evidence, as the account did before the cards. */
const unexplained = (detail: string): Pick<Story, 'args' | 'play'> => ({
  ...scenario({
    session: stored(
      reading({
        goal: GOAL_CONSISTENT,
        line_1: LINE_CONSISTENT,
        claims: { result: 'departure', cites: ['m1', 'c1'], detail, clause: '' },
      }),
    ),
    facts: [PERSON, PASSED, CLAIM, failedCheck('c1', 700)],
  }),
  play: async ({ canvasElement }) => {
    const shown = await result(await card(canvasElement));
    const claim = await waitFor(() => {
      const node = quietRow(shown, 'claims');
      expect(node).not.toBeNull();
      return node;
    });
    await expect(claim).toHaveAttribute('data-next-result-state', 'departs');
    await expect(claim.querySelector('.next-cockpit-reading-detail')).toHaveTextContent(
      /^No explanation was retained for this assessment\.$/,
    );
    await userEvent.click(within(claim).getByRole('button', { name: 'Evidence' }));
    const entries = await waitFor(() => {
      const found = [...claim.querySelectorAll<HTMLElement>('.next-cockpit-assessment-entry')];
      expect(found).toHaveLength(2);
      return found;
    });
    for (const entry of entries) {
      await waitFor(() => expect(entry).toBeVisible());
      await expect(entry).toHaveTextContent(/^\[\d+(\.\d+)?\] · /);
    }
    await neverDone(shown);
  },
});
export const ClaimContradictedWithNoDetail: Story = unexplained('');
export const ClaimContradictedWithBlankDetail: Story = unexplained('   ');

/* An agent message that says "Done" with a check mark, cited by a consistent line: the number names the entry by
   kind only, so the agent's words and mark never stand inside the result. The reading cites it twice, and it
   draws one number. */
export const AgentDoneIsNeverDrawnInTheResult: Story = {
  ...scenario({
    session: stored(
      reading({
        goal: { ...GOAL_CONSISTENT, cites: ['m2', 'm2'] },
        line_1: LINE_CONSISTENT,
      }),
    ),
    facts: [
      PERSON,
      PASSED,
      fact('m2', 650, { type: 'agent_message', by: 'agent', summary: 'Done ✓ the queue ships.' }),
    ],
  }),
  play: async ({ canvasElement }) => {
    const shown = await result(await card(canvasElement));
    const goal = await waitFor(() => {
      const node = quietRow(shown, 'goal');
      expect(node).not.toBeNull();
      return node;
    });
    await citesResolvably(goal, 'Goal', 'Ship the queue');
    await expect(chips(goal)).toHaveLength(1);
    await expect(chips(goal)[0]?.previousSibling?.textContent).toBe('Agent message');
    // The entry is in the record: Full activity, outside the result, still carries the agent's words.
    await expect(document.querySelector('[data-next-entry-id="m2"]')?.textContent ?? '').toContain(
      'the queue ships',
    );
    await neverDone(shown);
  },
};

/* One outcome line read: its card is labelled without a number. */
export const OneOutcomeLineDeparts: Story = {
  ...scenario({
    session: stored(
      reading({
        goal: GOAL_CONSISTENT,
        line_1: {
          result: 'departure',
          cites: ['c1'],
          detail: 'pytest failed after your words.',
          clause: 'Tests pass',
        },
      }),
    ),
    facts: [PERSON, FAILED],
  }),
  play: async ({ canvasElement }) => {
    const shown = await result(await card(canvasElement));
    const cards = await waitFor(() => {
      const found = departures(shown);
      expect(found).toHaveLength(1);
      return found;
    });
    await departureCard(
      cards[0] as HTMLElement,
      'Expected outcome',
      'Tests pass',
      'pytest failed after your words.',
      'Expected outcome line 1',
    );
    await expect(cards[0]?.querySelector('[data-next-departure-label]')).toHaveTextContent(
      /^Departure · Expected outcome$/,
    );
    await neverDone(shown);
  },
};

/* The agent's claim, shown by the record: at the check, as the tool reported. */
export const ClaimShownByTheRecord: Story = {
  ...scenario({
    session: stored(
      reading({
        goal: GOAL_CONSISTENT,
        line_1: LINE_CONSISTENT,
        claims: {
          result: 'consistent with the evidence read',
          cites: ['m1', 'c2'],
          detail: '',
          clause: '',
        },
      }),
    ),
    facts: [PERSON, CLAIM, passedCheck('c2', 700)],
  }),
  play: async ({ canvasElement }) => {
    const shown = await result(await card(canvasElement));
    const claim = await waitFor(() => {
      const node = quietRow(shown, 'claims');
      expect(node).not.toBeNull();
      return node;
    });
    await expect(claim).toHaveAttribute('data-next-result-state', 'consistent');
    await expect(claim).toHaveTextContent(
      /^What the agent claimed · “All green locally: the tests pass” is shown at \[\d+(\.\d+)?\]/,
    );
    await citesResolvably(claim, 'What the agent claimed', '');
    await neverDone(shown);
  },
};

/* The agent's claim, not shown by the record: about what was read, never that the thing did not happen. With no
   departure from the intent there is nothing to steer back from, so a claim alone offers no Steer back. */
export const ClaimNotShownOffersNoSteerBack: Story = {
  ...scenario({
    session: stored(
      reading({
        goal: GOAL_CONSISTENT,
        line_1: LINE_CONSISTENT,
        claims: {
          result: 'not shown by the record',
          cites: ['m1'],
          detail: '',
          clause: '',
        },
      }),
    ),
    facts: [PERSON, PASSED, CLAIM],
  }),
  play: async ({ canvasElement }) => {
    const drift = await card(canvasElement);
    const shown = await result(drift);
    const claim = await waitFor(() => {
      const node = quietRow(shown, 'claims');
      expect(node).not.toBeNull();
      return node;
    });
    await expect(claim).toHaveTextContent(
      /^What the agent claimed · “All green locally: the tests pass” is not shown by the record/,
    );
    // Its own reason: the claim names the tests, and the only check recorded is a lint run.
    await reasonInView(
      claim,
      'No test check was recorded in what was read, so nothing backs this claim.',
    );
    await citesResolvably(claim, 'What the agent claimed', '');
    await expect(within(drift).queryByRole('button', { name: 'Steer back' })).toBeNull();
    await expect(departures(shown)).toHaveLength(0);
    await neverDone(shown);
  },
};

/* The fourth claim state, can't tell, is never drawn as a row: the shape withdraws a claim it cannot place, and
   a withdrawn claim is the reading saying the agent made none it could check. */
export const ClaimItCannotTellIsNotDrawn: Story = {
  ...scenario({
    session: stored(
      reading({
        goal: GOAL_CONSISTENT,
        line_1: LINE_CONSISTENT,
        claims: {
          result: 'consistent with the evidence read',
          cites: ['m1'],
          detail: '',
          clause: '',
        },
      }),
    ),
    facts: [PERSON, PASSED, CLAIM],
  }),
  play: async ({ canvasElement }) => {
    const shown = await result(await card(canvasElement));
    await waitFor(() => expect(quietRow(shown, 'goal')).not.toBeNull());
    await expect(quietRow(shown, 'claims')).toBeNull();
    await expect(shown.textContent).not.toContain('What the agent said');
    await neverDone(shown);
  },
};

/* A later direction still unsettled: the question keeps the head of the card, and the result stays below it. */
export const PendingLaterDirection: Story = {
  ...scenario({
    session: stored(reading({ goal: GOAL_DEPARTS, line_1: LINE_CONSISTENT })),
    facts: [
      PERSON,
      FAILED,
      PASSED,
      fact('u2', 1100, {
        type: 'user_message',
        by: 'person:me',
        summary: 'Also add a retry to the queue worker.',
      }),
    ],
  }),
  play: async ({ canvasElement }) => {
    const drift = await card(canvasElement);
    const keep = await within(drift).findByRole('button', { name: 'Leave it' });
    const shown = await result(drift);
    await expect(shown.contains(keep)).toBe(true);
    await waitFor(() => expect(departures(shown)).toHaveLength(1));
    await expect(
      keep.compareDocumentPosition(departures(shown)[0] as HTMLElement) &
        Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    // While the question stands, Keep is the one primary, and Steer back stays beside the departures
    // as a secondary press from the check (owner, 2026-10-20), with no Update intent instead.
    const steer = await within(drift).findByRole('button', { name: 'Steer back' });
    await expect(steer).toHaveAttribute('data-variant', 'default');
    await expect(steer.closest('[data-next-result-steer]')).not.toBeNull();
    await expect(
      within(steer.closest('[data-next-steer-section]') as HTMLElement).getByRole('heading', {
        name: 'Steer back',
      }),
    ).toBeVisible();
    await expect(within(drift).queryByRole('button', { name: 'Update intent instead' })).toBeNull();
    await neverDone(shown);
  },
};

/* No reader on this machine: the stored reading still draws its cards, the reason stands where Analyze would,
   and Steer back is primary under a departure as before. */
export const NoReaderKeepsTheCards: Story = {
  ...scenario({
    session: stored(reading({ goal: GOAL_DEPARTS, line_1: LINE_CONSISTENT })),
    facts: [PERSON, FAILED, PASSED],
    route: routeFor('not-installed'),
  }),
  play: async ({ canvasElement }) => {
    const drift = await card(canvasElement);
    const shown = await result(drift);
    await waitFor(() => expect(departures(shown)).toHaveLength(1));
    await departureCard(
      departures(shown)[0] as HTMLElement,
      'Goal',
      'Ship the queue',
      'It stopped running the tests.',
      'Goal',
    );
    await expect(within(drift).queryByRole('button', { name: /^Analyze/ })).toBeNull();
    const steer = await within(drift).findByRole('button', { name: 'Steer back' });
    await expect(primaries(canvasElement)).toEqual([steer]);
    await neverDone(shown);
  },
};

/* A stored reading this build refused on read back: said in its own section, with no result and no header line. */
export const RefusedReading: Story = {
  ...scenario({ session: { annotation_reading_refused: true, annotation_reading_count: 1 } }),
  play: async ({ canvasElement }) => {
    const drift = await card(canvasElement);
    await expect(
      await within(drift).findByText(
        'A reading is stored for this session and this build could not read it, so nothing from it is shown. Asking again replaces it.',
      ),
    ).toBeVisible();
    await expect(within(drift).getByText(READING_DEFINITION)).toBeVisible();
    await expect(drift.querySelector('[data-next-result]')).toBeNull();
    await expect(drift.querySelector('[data-next-drift-stamp]')).toBeNull();
  },
};

/* A reading carrying a field this build does not know: no verdict of any kind, and no header line. */
export const MalformedReading: Story = {
  ...scenario({
    session: stored({ ...reading({ goal: GOAL_DEPARTS }), surprise: true }),
    facts: [PERSON, FAILED],
  }),
  play: async ({ canvasElement }) => {
    const drift = await card(canvasElement);
    await expect(await within(drift).findByText(UNKNOWN_KEY)).toBeVisible();
    await expect(within(drift).getByText('Unrecognised: surprise.')).toBeVisible();
    await expect(drift.querySelector('[data-next-result]')).toBeNull();
    await expect(drift.querySelector('[data-next-departure]')).toBeNull();
    await expect(drift.querySelector('[data-next-drift-stamp]')).toBeNull();
  },
};

/* A session blocked on the reader: the departure card stands and Steer back leads it (owner, 2026-10-20). */
export const BlockedSessionSteerBackIsNotPrimary: Story = {
  ...scenario({
    session: {
      state: 'needs_input',
      ...stored(reading({ goal: GOAL_DEPARTS, line_1: LINE_CONSISTENT })),
    },
    facts: [PERSON, FAILED, PASSED],
  }),
  play: async ({ canvasElement }) => {
    const drift = await card(canvasElement);
    const shown = await result(drift);
    await waitFor(() => expect(departures(shown)).toHaveLength(1));
    const steer = await within(drift).findByRole('button', { name: 'Steer back' });
    await expect(steer).toHaveAttribute('data-variant', 'primary');
    await neverDone(shown);
  },
};

/* A current Pi result: the same cards, and no Steer back, because Compass writes no correction for Pi. */
export const CurrentPiResult: Story = {
  ...scenario({
    harness: 'pi',
    session: stored(reading({ goal: GOAL_DEPARTS, line_1: LINE_CONSISTENT })),
    facts: [
      fact('u1', 200, { type: 'user_message', by: 'person:me', summary: 'Ship it' }, 'pi'),
      failedCheck('c1', 500, 'pi'),
      passedCheck('c2', 600, 'pi'),
    ],
  }),
  play: async ({ canvasElement }) => {
    const drift = await card(canvasElement);
    const shown = await result(drift);
    await waitFor(() => expect(departures(shown)).toHaveLength(1));
    await departureCard(
      departures(shown)[0] as HTMLElement,
      'Goal',
      'Ship the queue',
      'It stopped running the tests.',
      'Goal',
    );
    await stamp(drift);
    await expect(within(drift).queryByRole('button', { name: 'Steer back' })).toBeNull();
    await expect(primaries(canvasElement)).toHaveLength(0);
    await neverDone(shown);
  },
};

/* Mark as inaccurate and What the analysis read share one quiet footer row; the mark keeps its effect and Undo. */
export const FooterMarkAsInaccurateAndUndo: Story = {
  ...scenario({
    session: stored(reading({ goal: GOAL_DEPARTS, line_1: LINE_CONSISTENT })),
    /* The person's message after the failed check, so Steer back stands on the analysis alone and the mark is
       seen to withdraw it. */
    facts: [FAILED, fact('u1', 550, { type: 'user_message', by: 'person:me' }), PASSED],
    keepsMarks: true,
  }),
  play: async ({ canvasElement }) => {
    const drift = await card(canvasElement);
    const shown = await result(drift);
    const footer = await waitFor(() => {
      const node = shown.querySelector<HTMLElement>('[data-next-result-footer]');
      expect(node).not.toBeNull();
      return node as HTMLElement;
    });
    const mark = await within(footer).findByRole('button', { name: RESULT_NOT_ACCURATE });
    const read = within(footer).getByRole('button', { name: READ_SUMMARY });
    // One row: the two controls share a line at this width.
    await expect(
      Math.abs(mark.getBoundingClientRect().top - read.getBoundingClientRect().top),
    ).toBeLessThan(mark.getBoundingClientRect().height);
    await userEvent.click(mark);
    await waitFor(() =>
      expect(footer.querySelector('[data-next-result-mark]')).toHaveAttribute(
        'data-next-result-mark',
        'marked',
      ),
    );
    const notice = drift.querySelector<HTMLElement>('[data-next-drift-marked]') as HTMLElement;
    await expect(within(notice).getByRole('status')).toHaveTextContent(RESULT_MARKED);
    await expect(within(drift).queryByRole('button', { name: 'Steer back' })).toBeNull();
    await userEvent.click(within(notice).getByRole('button', { name: RESULT_UNMARK }));
    await waitFor(() =>
      expect(footer.querySelector('[data-next-result-mark]')).toHaveAttribute(
        'data-next-result-mark',
        'unmarked',
      ),
    );
    await within(drift).findByRole('button', { name: 'Steer back' });
  },
};

/* What the analysis read, from the footer: the model, the intent, the session and what is never read. */
export const FooterWhatTheAnalysisRead: Story = {
  ...scenario({
    session: stored(reading({ goal: GOAL_DEPARTS, line_1: LINE_CONSISTENT })),
    facts: [PERSON, FAILED, PASSED],
  }),
  play: async ({ canvasElement }) => {
    const drift = await card(canvasElement);
    const footer = await waitFor(() => {
      const node = drift.querySelector<HTMLElement>('[data-next-result-footer]');
      expect(node).not.toBeNull();
      return node as HTMLElement;
    });
    await userEvent.click(within(footer).getByRole('button', { name: READ_SUMMARY }));
    const read = await waitFor(() => {
      const node = drift.querySelector<HTMLElement>('[data-next-read]');
      expect(node).not.toBeNull();
      return node as HTMLElement;
    });
    await expect([...read.querySelectorAll('h4')].map((h) => h.textContent)).toEqual([
      'Model',
      'Your intent',
      'The session',
      'Not read',
    ]);
    // The model alone: the read time is the card header's, said once.
    await expect(read.querySelector('[data-next-read-section="model"]')).toHaveTextContent(
      /^Modelclaude-sonnet-5-5$/,
    );
    await expect(read.querySelector('[data-next-read-section="not-read"]')).toHaveTextContent(
      READ_NEVER,
    );
  },
};

/* Raised while you were away: the unasked lane's rows keep their own section under the result, collapsed under
   their count, and the reading's cards do not repeat them. */
export const RaisedWhileYouWereAway: Story = {
  ...scenario({
    payload: { unasked: true },
    session: {
      ...stored(reading({ goal: GOAL_DEPARTS, line_1: LINE_CONSISTENT })),
      departures: [
        {
          constraint: 'TYPED GOAL',
          at: 960,
          clause: 'Ship the queue',
          reading: 'It stopped running the tests.',
          revision: 3,
          cutoff: 970,
          evidence: 'pytest failed',
        },
      ],
      departure_checked: true,
    },
    facts: [PERSON, FAILED, PASSED],
  }),
  play: async ({ canvasElement }) => {
    const drift = await card(canvasElement);
    const shown = await result(drift);
    const away = await within(drift).findByRole('button', {
      name: 'Raised while you were away: 1',
    });
    await expect(
      shown.compareDocumentPosition(away) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    await expect(shown.contains(away)).toBe(false);
    await waitFor(() => expect(departures(shown)).toHaveLength(1));
  },
};
