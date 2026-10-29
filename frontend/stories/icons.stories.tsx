import type { Meta, StoryObj } from '@storybook/react-vite';
import { expect } from 'storybook/test';
import { Icon, type IconName } from '../src/ui/icons';
const names: IconName[] = [
  'unrecorded',
  'passed',
  'failed',
  'stale',
  'earlier-failed',
  'checks',
  'expand',
  'search',
  'check',
];
const meta = { title: 'UI/Icons', component: Icon, args: { name: 'unrecorded' } } satisfies Meta<
  typeof Icon
>;
export default meta;
type Story = StoryObj<typeof meta>;
export const Family: Story = {
  render: () => (
    <div>
      {names.map((name) => (
        <span key={name}>
          <Icon name={name} />
          {name}{' '}
        </span>
      ))}
    </div>
  ),
  play: async ({ canvasElement }) => {
    await expect(canvasElement.querySelectorAll('svg')).toHaveLength(names.length);
    for (const glyph of canvasElement.querySelectorAll('svg')) {
      await expect(glyph).toHaveAttribute('aria-hidden', 'true');
      await expect(glyph).toHaveAttribute('focusable', 'false');
    }
  },
};
