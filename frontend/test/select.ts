/* Storybook already ships user-event. Reuse its export without adding another dependency.
   Let its asyncWrapper own act; nesting user-event inside act leaves React's environment flag false. */
import { screen, waitFor } from '@testing-library/react';
import { userEvent } from 'storybook/test';

export async function openSelect(trigger: HTMLElement) {
  if (trigger.getAttribute('aria-expanded') !== 'true') {
    /* A Select opens on a key; a button that opens a list (the prompt control) opens on a press. */
    if (trigger.getAttribute('role') === 'combobox') {
      trigger.focus();
      await userEvent.setup().keyboard('{ArrowDown}');
    } else await userEvent.setup().click(trigger);
  }
  await waitFor(() => {
    if (trigger.getAttribute('aria-expanded') !== 'true')
      throw new Error('The choice did not open');
  });
}

export async function chooseSelect(trigger: HTMLElement, value: string) {
  await openSelect(trigger);
  const item = screen
    .getAllByRole('option')
    .find((option) => option.getAttribute('data-value') === value);
  if (!item) throw new Error(`The choice ${value} is absent`);
  await userEvent.setup().click(item);
}

export async function closeSelect() {
  await userEvent.setup().keyboard('{Escape}');
}
