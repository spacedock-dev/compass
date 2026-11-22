import type { Meta, StoryObj } from '@storybook/react-vite';
import { expect, userEvent, within } from 'storybook/test';
import { Switch } from '../src/ui/switch';
import { hasFocusRing, restingRing, rgbOf } from './a11y.audit';
import { expectSwitchPaint } from './switch.audit';

const meta = { title: 'UI/Switch', component: Switch } satisfies Meta<typeof Switch>;
export default meta;
type Story = StoryObj<typeof meta>;

export const States = {
  render: () => (
    <div style={{ maxWidth: 320, background: 'var(--panel)' }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <span id="switch-off">Off</span>
        <Switch aria-labelledby="switch-off" />
      </div>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <span id="switch-on">On</span>
        <Switch aria-labelledby="switch-on" defaultChecked />
      </div>
    </div>
  ),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const off = canvas.getByRole('switch', { name: 'Off' });
    const on = canvas.getByRole('switch', { name: 'On' });
    await expectSwitchPaint(off, false);
    await expectSwitchPaint(on, true);
    const resting = restingRing(off);
    await userEvent.tab();
    await expect(off).toHaveFocus();
    await expect(hasFocusRing(off, resting)).toBe(true);
    const focused = getComputedStyle(off);
    await expect(focused.outlineStyle).toBe('solid');
    await expect(focused.outlineWidth).toBe('2px');
    await expect(focused.outlineOffset).toBe('2px');
    await expect(rgbOf(focused.outlineColor)).toEqual(rgbOf(focused.getPropertyValue('--accent')));
    await userEvent.keyboard(' ');
    await expectSwitchPaint(off, true);
    await userEvent.click(off);
    await expectSwitchPaint(off, false);
  },
} satisfies Story;

export const PaintRejectsInvisibleThumb: Story = {
  render: States.render,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    for (const [name, checked] of [
      ['Off', false],
      ['On', true],
    ] as const) {
      const root = canvas.getByRole('switch', { name });
      const thumb = root.querySelector<HTMLElement>('[data-slot="switch-thumb"]');
      if (!thumb) throw new Error('Switch has no thumb to test');
      try {
        for (const opacity of ['0', '0.1']) {
          thumb.style.opacity = opacity;
          await expect(
            expectSwitchPaint(root, checked),
            `${name} with opacity ${opacity}`,
          ).rejects.toThrow('Thumb against track');
        }
      } finally {
        thumb.style.removeProperty('opacity');
      }
    }
  },
};

export const ForcedColors: Story = {
  render: States.render,
  play: async ({ canvasElement }) => {
    const browser = '__vitest_browser_runner__' in window ? await import('vitest/browser') : null;
    if (browser) await browser.commands.storyForcedColors('active');
    try {
      const forced = matchMedia('(forced-colors: active)').matches;
      if (browser) await expect(forced).toBe(true);
      const canvas = within(canvasElement);
      await expectSwitchPaint(canvas.getByRole('switch', { name: 'Off' }), false);
      await expectSwitchPaint(canvas.getByRole('switch', { name: 'On' }), true);
    } finally {
      if (browser) await browser.commands.storyForcedColors(null);
    }
  },
};
