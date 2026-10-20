import { userEvent, waitFor, within } from 'storybook/test';

/* A citation opens a card with the entry's words; the jump to Full activity is the card's own link. */
export async function seeInContext(citation: HTMLElement): Promise<void> {
  await userEvent.click(citation);
  const link = await waitFor(() =>
    within(document.body).getByText('See in context of the session'),
  );
  await userEvent.click(link);
}
