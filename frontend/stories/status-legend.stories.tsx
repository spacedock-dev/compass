import type { Meta, StoryObj } from '@storybook/react-vite';
import { expect, within } from 'storybook/test';
import { StatusLegend } from '../src/ui/status-legend';

const meta = { title: 'UI/Status legend', component: StatusLegend } satisfies Meta<
  typeof StatusLegend
>;
export default meta;
type Story = StoryObj<typeof meta>;

export const SessionStates: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const list = within(canvas.getByRole('list', { name: 'What the icons mean' }));
    const rows = list.getAllByRole('listitem');
    await expect(rows.map((row) => row.textContent)).toEqual([
      'Working',
      'Waiting on you',
      'Quiet',
      'Ended',
      'Worth a look',
    ]);
    await expect(rows[2]?.querySelector('[data-icon="quiet"]')).toBeVisible();
    await expect(rows[4]?.querySelector('[data-icon="worth-a-look"]')).toBeVisible();
  },
};
