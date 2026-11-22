import { expect } from 'storybook/test';

export async function expectSwitchPaint(root: HTMLElement, checked: boolean) {
  // The Node route-reason test also imports the unasked permission stories.
  const { contrastOf, paintedColors, rgbOf, settled } = await import('./a11y.audit');
  await settled();
  await expect(root).toHaveAttribute('aria-checked', String(checked));
  const target = root.getBoundingClientRect();
  await expect(target.width, 'Target width').toBeGreaterThanOrEqual(44);
  await expect(target.height, 'Target height').toBeGreaterThanOrEqual(44);

  const track = root.querySelector('[data-slot="switch-track"]');
  if (!track) throw new Error('Switch has no visible track');
  const box = track.getBoundingClientRect();
  await expect(box.width, 'Track width').toBe(52);
  await expect(box.height, 'Track height').toBe(30);
  const thumb = track.querySelector('[data-slot="switch-thumb"]');
  if (!thumb) throw new Error('Switch has no visible thumb');
  const knob = thumb.getBoundingClientRect();
  await expect(knob.width, 'Thumb width').toBe(24);
  await expect(knob.height, 'Thumb height').toBe(24);
  await expect(knob.left - box.left, 'Thumb offset').toBeCloseTo(checked ? 25 : 3);
  await expect(knob.top - box.top, 'Thumb vertical offset').toBeCloseTo(3);

  const thumbFill = getComputedStyle(thumb).backgroundColor;
  const fill = paintedColors(track, thumbFill);
  if (!fill) throw new Error('Cannot measure switch thumb and track paint');
  await expect(
    contrastOf(fill.foreground, fill.background),
    'Thumb against track',
  ).toBeGreaterThanOrEqual(3);
  if (checked) {
    const onAccent = getComputedStyle(root).getPropertyValue('--on-accent');
    await expect(rgbOf(thumbFill), 'Checked thumb paint').toEqual(rgbOf(onAccent));
  } else {
    const style = getComputedStyle(track);
    await expect(style.borderTopStyle, 'Off track boundary').toBe('solid');
    await expect(Number.parseFloat(style.borderTopWidth), 'Off track border width').toBeGreaterThan(
      0,
    );
    const border = paintedColors(root, style.borderTopColor);
    if (!border) throw new Error('Cannot measure the switch track against its surface');
    await expect(
      contrastOf(border.foreground, border.background),
      'Off track against surface',
    ).toBeGreaterThanOrEqual(3);
  }
}
