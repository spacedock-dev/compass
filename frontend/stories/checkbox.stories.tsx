import type { Meta, StoryObj } from '@storybook/react-vite';
import { expect, userEvent, within } from 'storybook/test';
import { Checkbox } from '../src/ui/checkbox';
import { Label } from '../src/ui/label';
const meta = { title: 'UI/Checkbox', component: Checkbox } satisfies Meta<typeof Checkbox>;
export default meta;
type Story = StoryObj<typeof meta>;
export const ToggledBySpaceAndLabel: Story = {
  render: () => (
    <div>
      <Label className="flex min-h-11 items-center gap-2">
        <Checkbox />
        compass
      </Label>
      <Label className="flex min-h-11 items-center gap-2">
        <Checkbox disabled />
        Droid
      </Label>
    </div>
  ),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const [box, off] = canvas.getAllByRole('checkbox') as [HTMLElement, HTMLElement];
    await expect(box).toHaveAttribute('aria-checked', 'false');
    box.focus();
    await userEvent.keyboard(' ');
    await expect(box).toHaveAttribute('aria-checked', 'true');
    // The whole row is the target: a press on the words toggles the box.
    await userEvent.click(canvas.getByText('compass'));
    await expect(box).toHaveAttribute('aria-checked', 'false');
    await expect(box.closest('label')?.getBoundingClientRect().height).toBeGreaterThanOrEqual(44);
    // A disabled box ignores both.
    await userEvent.click(canvas.getByText('Droid'));
    off.focus();
    await userEvent.keyboard(' ');
    await expect(off).toHaveAttribute('aria-checked', 'false');
    await expect(off).toHaveAttribute('aria-disabled', 'true');
  },
};
