import type { Meta, StoryObj } from '@storybook/react-vite';
import { expect, userEvent, within } from 'storybook/test';
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '../src/ui/tooltip';
const meta = { title: 'UI/Tooltip', component: TooltipContent } satisfies Meta<
  typeof TooltipContent
>;
export default meta;
type Story = StoryObj<typeof meta>;
export const NonFocusable: Story = {
  render: () => (
    <TooltipProvider delay={0}>
      <Tooltip>
        <TooltipTrigger render={<span />} aria-label="Full words">
          Short words
        </TooltipTrigger>
        <TooltipContent>Full words</TooltipContent>
      </Tooltip>
    </TooltipProvider>
  ),
  play: async ({ canvasElement }) => {
    const trigger = within(canvasElement).getByLabelText('Full words');
    await expect(trigger.tabIndex).toBe(-1);
    await userEvent.hover(trigger);
    const popup = await within(canvasElement.ownerDocument.body).findByRole('tooltip');
    await expect(popup).toHaveTextContent('Full words');
    await expect(getComputedStyle(popup).boxShadow).toContain('rgba(31, 41, 51, 0.18)');
  },
};
