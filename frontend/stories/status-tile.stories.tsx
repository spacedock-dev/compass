import type { Meta, StoryObj } from '@storybook/react-vite';
import { expect, userEvent, within } from 'storybook/test';
import { StatusTile } from '../src/ui/status-tile';
import { TooltipProvider } from '../src/ui/tooltip';

const meta = {
  title: 'UI/Status tile',
  component: StatusTile,
  decorators: [
    (Story) => (
      <TooltipProvider delay={0}>
        <Story />
      </TooltipProvider>
    ),
  ],
} satisfies Meta<typeof StatusTile>;
export default meta;
type Story = StoryObj<typeof meta>;

export const Quiet: Story = {
  args: { state: 'Quiet' },
  play: async ({ canvasElement }) => {
    const tile = within(canvasElement).getByRole('img', { name: 'Quiet' });
    await expect(tile).toBeVisible();
    await expect(tile.querySelector('svg[data-icon="quiet"]')).toBeVisible();
    const { width, height, borderRadius } = getComputedStyle(tile);
    await expect([width, height, borderRadius]).toEqual(['40px', '40px', '12px']);
    await userEvent.tab();
    await expect(tile).toHaveFocus();
    await expect(await within(document.body).findByRole('tooltip')).toHaveTextContent(/^Quiet$/);
    await userEvent.keyboard('{Escape}');
  },
};
