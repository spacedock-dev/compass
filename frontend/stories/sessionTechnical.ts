import { expect, userEvent, waitFor, within } from 'storybook/test';

export async function openSessionTechnicalTab(name: string, root: HTMLElement = document.body) {
  const scoped = within(root);
  const opener = await scoped.findByRole('button', { name: /^(Show|Hide) technical details$/ });
  if (opener.getAttribute('aria-expanded') !== 'true') await userEvent.click(opener);
  const tab = await scoped.findByRole('tab', { name });
  if (tab.getAttribute('aria-selected') !== 'true') await userEvent.click(tab);
  const panel = await scoped.findByRole('tabpanel', { name });
  await waitFor(() => expect(panel).toBeVisible());
  return within(panel);
}
