import type { Meta, StoryObj } from '@storybook/react-vite';
import { expect, userEvent, waitFor, within } from 'storybook/test';
import { DriftScenario, readingScenario, STORED_READING, type Scenario } from './drift.scenario';

/* The Session page against the redesign canvas (owner, 2026-11-24): Check progress filled in the header and
   repeated in Is it on track?, a tile per helper in Right now, bold At a glance numbers and the Project card's
   count of the project's other sessions today. Invented acme data throughout. */

const meta = {
  title: 'Sessions/Session page canvas',
  component: DriftScenario,
} satisfies Meta<typeof DriftScenario>;
export default meta;
type Story = StoryObj<typeof meta>;

const scenario = (value: Scenario): Pick<Story, 'args'> => ({ args: { scenario: value } });

const GREEN = 'rgb(47, 125, 91)';
const WHITE = 'rgb(255, 255, 255)';

async function header(canvasElement: HTMLElement): Promise<HTMLElement> {
  return waitFor(() => {
    const node = canvasElement.querySelector<HTMLElement>('[data-next-drift-status]');
    if (!node) throw new Error('no header press');
    return node;
  });
}

async function card(canvasElement: HTMLElement): Promise<HTMLElement> {
  return within(canvasElement).findByRole('region', { name: 'Is it on track?' });
}

async function cardPress(canvasElement: HTMLElement): Promise<HTMLElement> {
  const drift = await card(canvasElement);
  return waitFor(() => {
    const node = drift.querySelector<HTMLElement>('[data-next-drift-card-press]');
    if (!node) throw new Error('no card press');
    return node;
  });
}

export const HeaderCheckProgressIsFilledWithItsIconSpaced: Story = {
  ...scenario({}),
  play: async ({ canvasElement }) => {
    const press = within(await header(canvasElement)).getByRole('button', {
      name: 'Check progress',
    });
    await expect(press).not.toHaveAttribute('aria-disabled');
    const style = getComputedStyle(press);
    await expect(style.backgroundColor).toBe(GREEN);
    await expect(style.color).toBe(WHITE);
    await expect(style.borderTopLeftRadius).toBe('12px');
    await expect(style.fontWeight).toBe('600');
    // The glyph stands 8 px off its words.
    await expect(style.columnGap).toBe('8px');
    const glyph = press.querySelector('svg') as SVGElement;
    const label = document.createRange();
    label.selectNodeContents(press.lastChild as Node);
    await expect(
      label.getBoundingClientRect().left - glyph.getBoundingClientRect().right,
    ).toBeGreaterThanOrEqual(7.5);
  },
};

/* An unsettled later direction no longer drops the header's press to the outlined weight. */
export const HeaderCheckProgressAgainIsFilled: Story = {
  ...scenario({ session: STORED_READING }),
  play: async ({ canvasElement }) => {
    const press = within(await header(canvasElement)).getByRole('button', {
      name: 'Check progress again',
    });
    await expect(getComputedStyle(press).backgroundColor).toBe(GREEN);
    await expect(getComputedStyle(press).color).toBe(WHITE);
  },
};

const unchecked = readingScenario([]);

/* Not checked yet sits beside the way to check: the header's press, again in the card, with its Uses AI note.
   Pressing the card's copy starts the one check, and both copies give way to the running check. Finishing it
   and pressing the header's copy sends the identical request, because both are the one press. */
export const CardOffersCheckProgressBeforeAnyReading: Story = {
  ...scenario({ reading: unchecked }),
  play: async ({ canvasElement }) => {
    const drift = await card(canvasElement);
    await expect(await within(drift).findByText('Not checked yet')).toBeVisible();
    const inCard = within(await cardPress(canvasElement)).getByRole('button', {
      name: 'Check progress',
    });
    await expect(
      within(await header(canvasElement)).getByRole('button', { name: 'Check progress' }),
    ).toBeVisible();
    await expect(inCard).toBeVisible();
    await expect(within(await cardPress(canvasElement)).getByText('Uses AI')).toBeVisible();
    // Before a reading, with no other primary in the card, the card's copy is filled too.
    await expect(getComputedStyle(inCard).backgroundColor).toBe(GREEN);
    await userEvent.click(inCard);
    await waitFor(() => expect(unchecked.posts).toHaveLength(1));
    await waitFor(() =>
      expect(within(canvasElement).queryAllByRole('button', { name: 'Check progress' })).toEqual(
        [],
      ),
    );
    await expect(unchecked.posts).toHaveLength(1);
    await unchecked.finish?.();
    const again = within(await header(canvasElement)).getByRole('button', {
      name: 'Check progress',
    });
    await waitFor(() => expect(again).not.toHaveAttribute('aria-disabled'));
    await userEvent.click(again);
    await waitFor(() => expect(unchecked.posts).toHaveLength(2));
    await expect(unchecked.posts[1]).toEqual(unchecked.posts[0]);
  },
};

const rerun = readingScenario([]);

/* After a reading the card says Check progress again, outlined because Steer back and the reading own the
   card's emphasis. A press on it leaves both copies inert while the check runs, so the header cannot start a
   second one. */
export const CardOffersCheckProgressAgainAfterAReading: Story = {
  ...scenario({ session: STORED_READING, reading: rerun }),
  play: async ({ canvasElement }) => {
    const inCard = within(await cardPress(canvasElement)).getByRole('button', {
      name: 'Check progress again',
    });
    const inHeader = within(await header(canvasElement)).getByRole('button', {
      name: 'Check progress again',
    });
    await expect(within(await cardPress(canvasElement)).getByText('Uses AI')).toBeVisible();
    await expect(getComputedStyle(inCard).backgroundColor).not.toBe(GREEN);
    await expect(getComputedStyle(inHeader).backgroundColor).toBe(GREEN);
    await userEvent.click(inCard);
    await waitFor(() => expect(rerun.posts).toHaveLength(1));
    const copies = await waitFor(() => {
      const found = within(canvasElement).getAllByRole('button', { name: 'Check progress again' });
      for (const each of found) expect(each).toHaveAttribute('aria-disabled', 'true');
      return found;
    });
    await expect(copies).toHaveLength(2);
    await userEvent.click(copies[0] as HTMLElement);
    await expect(rerun.posts).toHaveLength(1);
  },
};

/* Undo changes before any edit is refused: calm, not the hatched dashed box the owner rejected on 2026-11-24. It
   stays a reachable button. */
export const UndoChangesRestsCalmBeforeAnEdit: Story = {
  ...scenario({}),
  play: async ({ canvasElement }) => {
    const goal = within(await within(canvasElement).findByRole('region', { name: 'Goal' }));
    await userEvent.click(await goal.findByRole('button', { name: 'Edit goal' }));
    const undo = await goal.findByRole('button', { name: 'Undo changes' });
    await expect(undo).toHaveAttribute('aria-disabled', 'true');
    const style = getComputedStyle(undo);
    await expect(style.backgroundImage).toBe('none');
    await expect(style.borderTopStyle).toBe('solid');
    await expect(style.borderTopLeftRadius).toBe('12px');
    await expect(style.backgroundColor).toBe('rgb(238, 241, 244)');
    undo.focus();
    await expect(undo).toHaveFocus();
  },
};

/* A refused press stays in both places, inert and calm: no hatch, a solid outline, the muted fill. */
export const RefusedCheckProgressIsCalmInBothPlaces: Story = {
  ...scenario({
    payload: { reading: { consent: false, off: true, reason: 'model-calls-paused' } },
  }),
  play: async ({ canvasElement }) => {
    const copies = await waitFor(() => {
      const found = within(canvasElement).getAllByRole('button', { name: 'Check progress' });
      if (found.length !== 2) throw new Error('both copies');
      return found;
    });
    for (const press of copies) {
      await expect(press).toHaveAttribute('aria-disabled', 'true');
      const style = getComputedStyle(press);
      await expect(style.backgroundImage).toBe('none');
      await expect(style.borderTopStyle).toBe('solid');
      await expect(style.backgroundColor).toBe('rgb(238, 241, 244)');
    }
  },
};

const HELPERS = {
  subagents: [
    { name: 'Docs writer', model: null, started_at: 1000, active: true, parent: null },
    { name: 'Test runner', model: null, started_at: 1000, active: false, parent: null },
    { name: 'Reviewer', model: null, started_at: null, active: null, parent: null },
  ],
};

/* Each helper has the canvas's 28 px tile. No harness records a helper's finish, so a stopped one is State not
   known, never Ended, with its words beside it. */
export const HelpersHaveTiles: Story = {
  ...scenario({ session: HELPERS }),
  play: async ({ canvasElement }) => {
    const list = await within(canvasElement).findByRole('list', { name: 'Helpers (3)' });
    for (const [name, tile, words] of [
      ['Docs writer', 'Working', ''],
      ['Test runner', 'State not known', 'Not running'],
      ['Reviewer', 'State not known', 'Activity not published'],
    ] as const) {
      const row = within(list).getByText(name).closest('li') as HTMLElement;
      const picture = within(row).getByRole('img', { name: tile });
      await expect(picture).toBeVisible();
      const { width, height } = picture.getBoundingClientRect();
      await expect([width, height]).toEqual([28, 28]);
      await expect(picture).not.toHaveAttribute('tabindex');
      if (words) await expect(row).toHaveTextContent(words);
    }
    await expect(within(list).queryByRole('img', { name: 'Ended' })).toBeNull();
  },
};

/* The numbers lead their labels: the 24 px step at 800. */
export const AtAGlanceNumbersLead: Story = {
  ...scenario({ session: { session_output_tokens: 4200, turn_output_tokens: 310 } }),
  play: async ({ canvasElement }) => {
    const glance = await within(canvasElement).findByRole('region', { name: 'At a glance' });
    const value = await within(glance).findByText('4,200');
    const style = getComputedStyle(value);
    await expect(style.fontSize).toBe('24px');
    await expect(style.fontWeight).toBe('800');
    await expect(getComputedStyle(within(glance).getByText('Session output tokens')).fontSize).toBe(
      '13px',
    );
  },
};

const other = (sid: string, fields: Record<string, unknown>) => ({
  harness: 'codex',
  sid,
  project: 'demo',
  project_key: '/demo',
  title: `Acme ${sid}`,
  ...fields,
});

async function projectLine(canvasElement: HTMLElement): Promise<HTMLElement> {
  return within(canvasElement).findByRole('region', { name: 'Project' });
}

export const ProjectCountsOtherSessionsToday: Story = {
  ...scenario({
    others: [other('a', { state: 'working' }), other('b', { state: 'needs_input' })],
  }),
  play: async ({ canvasElement }) => {
    const project = await projectLine(canvasElement);
    await expect(
      await within(project).findByText('2 other sessions today · 1 working'),
    ).toBeVisible();
    // The canvas's 8 px under the heading.
    const heading = within(project).getByRole('heading', { name: 'Project' });
    const link = within(project).getByRole('link', { name: 'demo' });
    await expect(
      link.getBoundingClientRect().top - heading.getBoundingClientRect().bottom,
    ).toBeLessThanOrEqual(10);
  },
};

export const ProjectCountsOneOtherSession: Story = {
  ...scenario({ others: [other('a', { state: 'working' })] }),
  play: async ({ canvasElement }) => {
    const project = await projectLine(canvasElement);
    await expect(
      await within(project).findByText('1 other session today · 1 working'),
    ).toBeVisible();
  },
};

export const ProjectSaysNothingWithNoOtherSessionToday: Story = {
  ...scenario({ others: [other('a', { state: 'idle' })] }),
  play: async ({ canvasElement }) => {
    const project = await projectLine(canvasElement);
    await expect(within(project).getByRole('link', { name: 'demo' })).toBeVisible();
    await expect(project.querySelector('[data-next-session-project-today]')).toBeNull();
    await expect(project).not.toHaveTextContent(/other session/);
  },
};
