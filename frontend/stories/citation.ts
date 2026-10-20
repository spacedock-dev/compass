import { userEvent, waitFor, within } from 'storybook/test';

/* A citation opens a card with the entry's words; the jump to Full activity is the card's own link. */
export async function seeInContext(citation: HTMLElement): Promise<void> {
  await userEvent.click(citation);
  const link = await waitFor(() =>
    within(document.body).getByText('See in context of the session'),
  );
  await userEvent.click(link);
}

/* The summary's phases are folded by default; a story that reads their lines opens them first. */
export async function openPhases(summary: HTMLElement): Promise<void> {
  for (const phase of summary.querySelectorAll<HTMLElement>('[data-next-summary-phase]')) {
    const trigger = phase.querySelector<HTMLElement>('[data-slot="accordion-trigger"]');
    if (trigger?.getAttribute('aria-expanded') === 'false') await userEvent.click(trigger);
  }
}
