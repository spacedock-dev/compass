import type { Meta, StoryObj } from '@storybook/react-vite';
import { useState } from 'react';
import { expect, fireEvent, userEvent, waitFor } from 'storybook/test';
import { Slider } from '../src/ui/slider';

const sizes = ['16 KB', '32 KB', '64 KB', '128 KB', '256 KB'];
const size = (stop: number): string => sizes[stop] ?? '';

function SliderExample({ locked }: { readonly locked: boolean }) {
  const [value, setValue] = useState(1);
  const [saved, setSaved] = useState(1);
  return (
    <section aria-label="Prompt size example" className="max-w-[28rem] text-body">
      <Slider
        label="Prompt size"
        value={value}
        recommended={2}
        lastStop={sizes.length - 1}
        disabled={locked}
        valueText={size}
        onChange={setValue}
        onRelease={setSaved}
        onCancel={() => setValue(saved)}
      />
      <p role="status">{`Saved: ${size(saved)}.`}</p>
    </section>
  );
}

const meta = {
  title: 'UI/Slider',
  component: SliderExample,
  args: { locked: false },
} satisfies Meta<typeof SliderExample>;
export default meta;
type Story = StoryObj<typeof meta>;

export const ArrowKeysSaveOnRelease: Story = {
  play: async ({ canvas }) => {
    const slider = canvas.getByRole('slider', { name: 'Prompt size' });
    await expect(slider).toHaveAttribute('aria-valuetext', '32 KB');
    await userEvent.tab();
    await expect(slider).toHaveFocus();
    const control = slider.closest('[data-slot="slider-control"]');
    await expect(control?.getBoundingClientRect().height).toBeGreaterThanOrEqual(44);
    fireEvent.keyDown(slider, { key: 'ArrowRight' });
    await waitFor(() => expect(slider).toHaveAttribute('aria-valuetext', '64 KB'));
    fireEvent.keyDown(slider, { key: 'ArrowRight', repeat: true });
    await waitFor(() => expect(slider).toHaveAttribute('aria-valuetext', '128 KB'));
    await expect(canvas.getByRole('status')).toHaveTextContent('Saved: 32 KB.');
    await expect(canvas.queryByText('Saved: 128 KB.')).toBeNull();
    fireEvent.keyUp(slider, { key: 'ArrowRight' });
    await waitFor(() => expect(canvas.getByRole('status')).toHaveTextContent('Saved: 128 KB.'));
    await expect(canvas.queryByText('Saved: 32 KB.')).toBeNull();
  },
};

export const LockedSliderRetainsTheSavedStop: Story = {
  args: { locked: true },
  play: async ({ canvas }) => {
    const slider = canvas.getByRole('slider', { name: 'Prompt size' });
    await expect(slider).toHaveAttribute('aria-disabled', 'true');
    await userEvent.tab();
    await expect(slider).toHaveFocus();
    await userEvent.keyboard('{End}');
    await expect(slider).toHaveAttribute('aria-valuetext', '32 KB');
    await expect(canvas.getByRole('status')).toHaveTextContent('Saved: 32 KB.');
    await expect(canvas.queryByText('Saved: 256 KB.')).toBeNull();
  },
};
