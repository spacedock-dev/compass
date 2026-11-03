import type { Meta, StoryObj } from '@storybook/react-vite';
import { expect, userEvent, waitFor, within } from 'storybook/test';
import { STORE_BUSY_PRESS, STORE_UNREADABLE_PRESS } from '../src/drift/sentences';
import { DriftScenario, fact, type Scenario } from './drift.scenario';

/* Analyze drift pressed while the store of what the reader typed cannot take the press. The server answers
   503 with the cause, nothing has started or been spent, and the card names the cause beside the button
   rather than saying the answer was lost. The sentence is itself the card's polite live region, so what is
   drawn and what a screen reader is told are one node. */

const meta = {
  title: 'Drift/Store refusal',
  component: DriftScenario,
} satisfies Meta<typeof DriftScenario>;
export default meta;
type Story = StoryObj<typeof meta>;

const scenario = (value: Scenario): Pick<Story, 'args'> => ({ args: { scenario: value } });
const PERSON = fact('u1', 200, { type: 'user_message', by: 'person:me', summary: 'Ship it' });

/* The server's own sentence for an annotation file it could not read (`annotations.STORE_UNREADABLE`). */
const NOTICE =
  'Compass could not read compass-annotations.json, so what you typed against sessions cannot be shown and nothing will be saved over it. Move or repair that file to save again.';

async function pressAnalyze(canvasElement: HTMLElement): Promise<HTMLElement> {
  const card = await within(canvasElement).findByRole('region', { name: 'Drift' });
  await userEvent.click(await within(card).findByRole('button', { name: 'Analyze drift' }));
  return card;
}

export const BusyStoreSaysSoAndStartsNothing: Story = {
  ...scenario({
    facts: [PERSON],
    readingStoreRefusal: {
      body: { ok: false, reason: 'annotation-store-busy' },
      posts: 0,
    },
  }),
  play: async ({ canvasElement, args }) => {
    const card = await pressAnalyze(canvasElement);
    const said = await within(card).findByRole('status');
    await expect(said).toHaveTextContent(STORE_BUSY_PRESS);
    await expect(card).not.toHaveTextContent('Could not confirm the reading');
    await expect(card).not.toHaveTextContent('has not been retried');
    // The sentence and the live region are one node, so the two cannot disagree.
    await expect(within(card).getAllByText(STORE_BUSY_PRESS)).toHaveLength(1);
    await expect(args.scenario.readingStoreRefusal?.posts).toBe(1);
    await expect(card.querySelector('[data-next-analyzing]')).toBeNull();
  },
};

export const UnreadableStoreSaysSoAndPointsAtTheCardNotice: Story = {
  ...scenario({
    facts: [PERSON],
    readingStoreRefusal: {
      body: { ok: false, reason: 'annotation-store-unavailable' },
      after: { annotate_unreadable: NOTICE },
      posts: 0,
    },
  }),
  play: async ({ canvasElement }) => {
    const card = await pressAnalyze(canvasElement);
    const said = await within(card).findByRole('status');
    await expect(said).toHaveTextContent(STORE_UNREADABLE_PRESS);
    await expect(card).not.toHaveTextContent('Could not confirm the reading');
    // The notice the sentence points at is drawn on the Intent card, with the repair step.
    const intent = await within(canvasElement).findByRole('region', { name: 'Intent' });
    await waitFor(() =>
      expect(intent).toHaveTextContent('Move or repair that file to save again.'),
    );
  },
};
