import type { Meta, StoryObj } from '@storybook/react-vite';
import { expect, userEvent, within, waitFor } from 'storybook/test';
import { Popover, PopoverTrigger, PopoverContent } from '../src/ui/popover';
import { Button } from '../src/ui/button';
const meta = { title: 'UI/Popover', component: Popover } satisfies Meta<typeof Popover>;
export default meta;
type Story = StoryObj<typeof meta>;
export const Keyboard: Story = {
  render: () => (
    <Popover>
      <PopoverTrigger>Why</PopoverTrigger>
      <PopoverContent aria-label="Why">
        <p>Because of the board</p>
        <Button>Inside why</Button>
      </PopoverContent>
    </Popover>
  ),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const body = within(canvasElement.ownerDocument.body);
    const trigger = canvas.getByRole('button', { name: 'Why' });
    trigger.focus();
    await userEvent.keyboard('{Enter}');
    const popup = await body.findByRole('dialog', { name: 'Why' });
    await waitFor(() => expect(popup).toBeVisible());
    await expect(getComputedStyle(popup).boxShadow).toContain('rgba(31, 41, 51, 0.18)');
    await userEvent.keyboard('{Escape}');
    await waitFor(() => expect(trigger).toHaveAttribute('aria-expanded', 'false'));
    await waitFor(() => expect(trigger).toHaveFocus());
    await userEvent.keyboard(' ');
    await waitFor(() => expect(body.getByRole('dialog', { name: 'Why' })).toBeVisible());
    await userEvent.keyboard('{Escape}');
    await waitFor(() => expect(trigger).toHaveFocus());
  },
};
