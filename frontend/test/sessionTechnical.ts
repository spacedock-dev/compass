import { act, fireEvent, screen } from '@testing-library/react';

export async function openSessionTechnicalTab(name: string) {
  await act(async () => {
    const opener = screen.queryByRole('button', { name: 'Show technical details' });
    if (opener) fireEvent.click(opener);
  });
  await act(async () => {
    const tab = screen.getByRole('tab', { name });
    if (tab.getAttribute('aria-selected') !== 'true') fireEvent.click(tab);
  });
}
