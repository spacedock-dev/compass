/* shadcn Slider, Base UI flavour. CLI: shadcn@4.21.4.
   Registry: https://ui.shadcn.com/r/styles/base-nova/slider.json
   Upstream content SHA-256: 1fd32ee03ddaa382aabccce0bd88669aa8f91e4fe487622a68745d2ed1d5f5b9
   MIT. The full upstream notice ships in react-licenses.txt.
   Single thumb with discrete stop indexes, a 44px control, and release-only commits. */
import { Slider as Primitive } from '@base-ui/react/slider';
import { useLayoutEffect, useRef } from 'react';

interface SliderProps {
  readonly label: string;
  readonly description?: string;
  readonly value: number;
  readonly lastStop: number;
  readonly recommended: number;
  readonly disabled?: boolean;
  readonly valueText: (index: number) => string;
  readonly onChange: (index: number) => void;
  readonly onRelease: (index: number) => void;
  readonly onCancel: () => void;
}

export function Slider({
  label,
  description,
  value,
  lastStop,
  recommended,
  disabled,
  valueText,
  onChange,
  onRelease,
  onCancel,
}: SliderProps) {
  const input = useRef<HTMLInputElement>(null);
  useLayoutEffect(() => {
    if (disabled) input.current?.setAttribute('aria-disabled', 'true');
    else input.current?.removeAttribute('aria-disabled');
  }, [disabled]);
  const key = useRef<{ readonly name: string; readonly value: number } | null>(null);
  return (
    <Primitive.Root
      data-slot="slider"
      className="group"
      value={value}
      min={0}
      max={lastStop}
      aria-disabled={disabled || undefined}
      onValueChange={(next, detail) => {
        if (disabled) detail.cancel();
        else onChange(next);
      }}
      onValueCommitted={(next, detail) => {
        if (disabled) return;
        // Base UI commits keyboard changes on every keydown, including repeats.
        if (detail.reason === 'keyboard' && detail.event instanceof KeyboardEvent) {
          key.current = { name: detail.event.key, value: next };
        } else if (detail.event.type === 'pointermove') {
          onCancel();
        } else {
          onRelease(next);
        }
      }}
      onPointerCancel={onCancel}
      onBlur={() => {
        if (!key.current) return;
        key.current = null;
        onCancel();
      }}
      onKeyUp={(event) => {
        const held = key.current;
        if (!held || held.name !== event.key) return;
        key.current = null;
        if (!disabled) onRelease(held.value);
      }}
    >
      <Primitive.Control
        data-slot="slider-control"
        className="flex min-h-[44px] cursor-pointer touch-pan-y items-center px-2 group-aria-disabled:cursor-not-allowed"
      >
        <Primitive.Track className="relative h-2 w-full rounded-pill border border-solid border-input bg-muted">
          <Primitive.Indicator className="h-full rounded-pill bg-[var(--accent-dim)] forced-colors:bg-[Highlight]" />
          <span
            aria-hidden="true"
            className="absolute top-4 size-1.5 -translate-x-1/2 rounded-full bg-[var(--accent-dim)] forced-colors:bg-[CanvasText]"
            style={{ left: `${(recommended / lastStop) * 100}%` }}
          />
          <Primitive.Thumb
            data-slot="slider-thumb"
            aria-label={label}
            inputRef={input}
            aria-describedby={description}
            getAriaValueText={(_, index) => valueText(index)}
            className="block size-4 rounded-full border border-solid border-[var(--accent-dim)] bg-[var(--accent-dim)] has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-solid has-[:focus-visible]:outline-ring has-[:focus-visible]:outline-offset-2 forced-colors:border-[CanvasText]"
          />
        </Primitive.Track>
      </Primitive.Control>
    </Primitive.Root>
  );
}
