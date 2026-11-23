import { fireEvent, render, screen } from '@testing-library/react';
import { useState } from 'react';
import { describe, expect, it, vi } from 'vitest';
import { Slider } from './slider';

function mount() {
  const save = vi.fn();
  const cancel = vi.fn();
  function Example() {
    const [value, setValue] = useState(0);
    return (
      <Slider
        label="Prompt size"
        value={value}
        lastStop={4}
        recommended={2}
        valueText={(index) => `${index * 64} KB`}
        onChange={setValue}
        onRelease={save}
        onCancel={cancel}
      />
    );
  }
  const { container } = render(<Example />);
  return { save, cancel, container, thumb: screen.getByRole('slider', { name: 'Prompt size' }) };
}

describe('committing a stepped slider', () => {
  it('saves exactly once after an arrow key held across repeated keydowns is released', () => {
    const { save, thumb } = mount();
    for (let index = 0; index < 3; index += 1)
      fireEvent.keyDown(thumb, { key: 'ArrowRight', repeat: index > 0 });
    expect(thumb.getAttribute('aria-valuetext')).toBe('192 KB');
    expect(save).not.toHaveBeenCalled();
    fireEvent.keyUp(thumb, { key: 'ArrowRight' });
    fireEvent.keyUp(thumb, { key: 'ArrowRight' });
    expect(save).toHaveBeenCalledExactlyOnceWith(3);
  });

  it('saves a track drag only on pointer release', () => {
    const { save, container } = mount();
    const control = container.querySelector('[data-slot="slider-control"]');
    if (!control) throw new Error('Missing slider control');
    Object.defineProperty(control, 'hasPointerCapture', { value: () => false });
    vi.spyOn(control, 'getBoundingClientRect').mockReturnValue(new DOMRect(0, 0, 100, 44));
    fireEvent.pointerDown(control, { button: 0, buttons: 1, clientX: 25, clientY: 22 });
    fireEvent.pointerMove(document, { buttons: 1, clientX: 75, clientY: 22 });
    expect(save).not.toHaveBeenCalled();
    fireEvent.pointerUp(document, { button: 0, buttons: 0, clientX: 75, clientY: 22 });
    expect(save).toHaveBeenCalledExactlyOnceWith(3);
  });
});
