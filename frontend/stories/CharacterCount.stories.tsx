import type { Meta, StoryObj } from '@storybook/react-vite';
import { expect, within } from 'storybook/test';
import { CharacterCount } from '../src/ui/CharacterCount';

const meta = {
  title: 'UI/Character count',
  component: CharacterCount,
  args: { id: 'character-count', length: 1500, limit: 2000 },
} satisfies Meta<typeof CharacterCount>;
export default meta;
type Story = StoryObj<typeof meta>;

export const BelowEightyPercent: Story = {
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).queryByText('1500/2000')).toBeNull();
    await expect(canvasElement.querySelector('[data-character-count]')).toBeNull();
  },
};

export const AtEightyPercent: Story = {
  args: { length: 1600 },
  play: async ({ canvasElement }) => {
    const count = within(canvasElement).getByText('1600/2000');
    await expect(count).toBeVisible();
    await expect(count).not.toHaveAttribute('data-over');
  },
};

export const AtTheLimit: Story = {
  args: { length: 2000 },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText('2000/2000')).toBeVisible();
    await expect(canvas.getByText('2000/2000')).not.toHaveAttribute('data-over');
    await expect(canvas.getByRole('status')).toBeEmptyDOMElement();
  },
};

export const OverTheLimit: Story = {
  args: { length: 2100 },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText('2100/2000')).toHaveAttribute('data-over', 'true');
    await expect(canvas.getByRole('status')).toHaveTextContent(
      '2100 characters; the limit is 2000.',
    );
  },
};
