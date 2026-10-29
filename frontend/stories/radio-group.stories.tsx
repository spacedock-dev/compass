import type { Meta, StoryObj } from '@storybook/react-vite';
import { expect, userEvent, within } from 'storybook/test';
import { Label } from '../src/ui/label';
import { RadioGroup, RadioGroupItem } from '../src/ui/radio-group';
const meta = { title: 'UI/Radio Group', component: RadioGroup } satisfies Meta<typeof RadioGroup>;
export default meta;
type Story = StoryObj<typeof meta>;
const CHOICES = ['Any time', 'Today', 'Yesterday'];
export const ArrowsMoveTheChoice: Story = {
  render: () => (
    <RadioGroup aria-label="When" defaultValue="Any time">
      {CHOICES.map((choice) => (
        <Label key={choice} className="flex min-h-11 items-center gap-2">
          <RadioGroupItem value={choice} />
          {choice}
        </Label>
      ))}
    </RadioGroup>
  ),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const group = canvas.getByRole('radiogroup', { name: 'When' });
    const radios = within(group).getAllByRole('radio');
    const checked = () => radios.filter((one) => one.getAttribute('aria-checked') === 'true');
    await expect(checked()).toHaveLength(1);
    // One tab stop: only the checked item is in the tab order.
    await expect(radios.filter((one) => one.tabIndex === 0)).toHaveLength(1);
    (radios[0] as HTMLElement).focus();
    await userEvent.keyboard('{ArrowDown}');
    await expect(radios[1]).toHaveAttribute('aria-checked', 'true');
    await expect(radios[1]).toHaveFocus();
    await expect(checked()).toHaveLength(1);
    await userEvent.click(canvas.getByText('Yesterday'));
    await expect(radios[2]).toHaveAttribute('aria-checked', 'true');
    await expect(checked()).toHaveLength(1);
  },
};
