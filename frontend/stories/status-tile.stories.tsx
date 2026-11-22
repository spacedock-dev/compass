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
    const glyph = tile.querySelector('svg[data-icon="quiet"]');
    await expect(glyph).toBeVisible();
    const { width, height } = tile.getBoundingClientRect();
    await expect(width).toBeGreaterThanOrEqual(44);
    await expect(height).toBeGreaterThanOrEqual(44);
    const artwork = getComputedStyle(glyph?.parentElement as HTMLElement);
    await expect([artwork.width, artwork.height, artwork.borderRadius]).toEqual([
      '40px',
      '40px',
      '12px',
    ]);
    await userEvent.tab();
    await expect(tile).toHaveFocus();
    await expect(await within(document.body).findByRole('tooltip')).toHaveTextContent(/^Quiet$/);
    await userEvent.keyboard('{Escape}');
  },
};
