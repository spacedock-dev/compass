import type { Meta, StoryObj } from '@storybook/react-vite';
import { expect, userEvent, within, waitFor } from 'storybook/test';
import { useState } from 'react';
import { Select, SelectTrigger, SelectValue, SelectContent, SelectItem } from '../src/ui/select';

const meta = { title: 'UI/Select', component: SelectTrigger } satisfies Meta<typeof SelectTrigger>;
export default meta;
type Story = StoryObj<typeof meta>;
const long =
  "A long choice whose chevron must leave room for the reader's text and whose complete sentence is available when it wraps beyond two lines";

function Example({ disabled = false, loading = false }: { disabled?: boolean; loading?: boolean }) {
  const [pending, setPending] = useState(loading);
  return (
    <Select
      disabled={disabled}
      items={{ long, short: 'Short choice' }}
      defaultValue={loading ? null : 'long'}
    >
      <SelectTrigger
        aria-label="Example choice"
        aria-busy={pending}
        style={{ width: '18rem', maxWidth: '100%' }}
      >
        <SelectValue placeholder="Use your prompt" />
      </SelectTrigger>
      <SelectContent>
        {pending ? (
          <SelectItem value="loading" disabled>
            Loading your prompts
          </SelectItem>
        ) : (
          <>
            <SelectItem value="long">{long}</SelectItem>
            <SelectItem value="short">Short choice</SelectItem>
          </>
        )}
      </SelectContent>
      {pending ? (
        <button type="button" onClick={() => setPending(false)}>
          Finish loading
        </button>
      ) : null}
    </Select>
  );
}

export const KeyboardAndLongText: Story = {
  render: () => <Example />,
  play: async ({ canvasElement }) => {
    const trigger = within(canvasElement).getByRole('combobox', { name: 'Example choice' });
    await userEvent.click(trigger);
    const page = within(canvasElement.ownerDocument.body);
    await expect(await page.findByRole('option', { name: long })).toHaveAttribute('title', long);
    const list = await page.findByRole('listbox');
    await expect(list).toBeVisible();
    const popup = list.closest('[data-slot="select-content"]');
    if (!popup) throw new Error('Expected the listbox inside a select popup');
    await expect(getComputedStyle(popup).boxShadow).toContain('rgba(31, 41, 51, 0.18)');
    await waitFor(() =>
      expect(list.contains(canvasElement.ownerDocument.activeElement)).toBe(true),
    );
    await userEvent.keyboard('{End}{Enter}');
    await waitFor(() => expect(trigger).toHaveTextContent('Short choice'));
    await expect(trigger).toHaveAttribute('aria-expanded', 'false');
  },
};
export const Disabled: Story = {
  render: () => <Example disabled />,
  play: async ({ canvasElement }) => {
    const trigger = within(canvasElement).getByRole('combobox');
    await expect(trigger).toBeDisabled();
    await userEvent.click(trigger);
    await expect(trigger).toHaveAttribute('aria-expanded', 'false');
  },
};
export const Loading: Story = {
  render: () => <Example loading />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const trigger = canvas.getByRole('combobox');
    const width = trigger.getBoundingClientRect().width;
    await userEvent.click(trigger);
    const page = within(canvasElement.ownerDocument.body);
    await expect(await page.findByRole('option', { name: 'Loading your prompts' })).toHaveAttribute(
      'aria-disabled',
      'true',
    );
    await expect(trigger).toHaveAttribute('aria-busy', 'true');
    // Resolve asynchronously without moving focus out of the popup.
    canvas.getByRole('button', { name: 'Finish loading' }).click();
    await expect(await page.findByRole('option', { name: 'Short choice' })).toBeVisible();
    await expect(trigger).toHaveAttribute('aria-expanded', 'true');
    await expect(trigger).toHaveAttribute('aria-busy', 'false');
    await expect(trigger.getBoundingClientRect().width).toBe(width);
    await userEvent.click(page.getByRole('option', { name: 'Short choice' }));
    await waitFor(() => expect(trigger).toHaveTextContent('Short choice'));
  },
};

export const Scrolling: Story = {
  render: () => (
    <Select
      items={Array.from({ length: 30 }, (_, n) => ({
        value: String(n),
        label: `Stage ${String(n + 1)}`,
      }))}
      defaultValue="0"
    >
      <SelectTrigger aria-label="Many stages" style={{ width: '18rem', maxWidth: '100%' }}>
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        {Array.from({ length: 30 }, (_, n) => (
          <SelectItem key={n} value={String(n)}>{`Stage ${String(n + 1)}`}</SelectItem>
        ))}
      </SelectContent>
    </Select>
  ),
  play: async ({ canvasElement }) => {
    const trigger = within(canvasElement).getByRole('combobox');
    await userEvent.click(trigger);
    const page = within(canvasElement.ownerDocument.body);
    const list = await page.findByRole('listbox');
    await expect(list.scrollHeight).toBeGreaterThan(list.clientHeight);
    await waitFor(() =>
      expect(list.contains(canvasElement.ownerDocument.activeElement)).toBe(true),
    );
    await userEvent.keyboard('{End}');
    await waitFor(() => expect(list.scrollTop).toBeGreaterThan(0));
    const last = page.getByRole('option', { name: 'Stage 30' });
    await expect(last.getBoundingClientRect().bottom).toBeLessThanOrEqual(
      list.getBoundingClientRect().bottom + 1,
    );
    await userEvent.keyboard('{Enter}');
    await waitFor(() => expect(trigger).toHaveTextContent('Stage 30'));
  },
};

export const NearTheBottomOfTheScreen: Story = {
  render: () => (
    <div style={{ position: 'fixed', insetInline: 0, bottom: 8 }}>
      <Example />
    </div>
  ),
  play: async ({ canvasElement }) => {
    const trigger = within(canvasElement).getByRole('combobox', { name: 'Example choice' });
    await userEvent.click(trigger);
    const popup = await within(canvasElement.ownerDocument.body).findByRole('listbox');
    // With no room below, the list opens above the trigger instead of collapsing to a sliver.
    await waitFor(() => {
      expect(popup.getBoundingClientRect().bottom).toBeLessThanOrEqual(
        trigger.getBoundingClientRect().top + 1,
      );
      expect(popup.getBoundingClientRect().height).toBeGreaterThan(44);
    });
  },
};
