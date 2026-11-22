/* shadcn Select, Base UI flavour. CLI: shadcn@4.21.4.
   Registry: https://ui.shadcn.com/r/styles/base-nova/select.json
   Upstream content SHA-256: 6918ba753234e510c57db3fe395f8b67936421db1efa2ed88694d186aa736c59
   MIT; the full upstream notice ships in react-licenses.txt.
   Deviations: local cn, inline chevrons/check, page tokens and fieldBase, no size variants,
   animations or registry cn-menu classes. Non-modal popups drop below the trigger instead of
   aligning the selected item over it, with viewport bounds, list-owned scrolling and two-line titled items.
   String item values expose data-value for source-identity proofs.
   docs/design-shadcn-adoption.md#form-controls-layer owns the tuning. */
import type { ComponentProps } from 'react';
import { Select as SelectPrimitive } from '@base-ui/react/select';
import { cn } from '../lib/utils';
import { fieldBase } from './input';

export function Select<Value, Multiple extends boolean | undefined = false>(
  props: SelectPrimitive.Root.Props<Value, Multiple>,
) {
  return <SelectPrimitive.Root modal={false} {...props} />;
}

function Chevron({ up = false }: { up?: boolean }) {
  return (
    <svg
      aria-hidden="true"
      viewBox="0 0 10 10"
      width="10"
      height="10"
      fill="none"
      className="pointer-events-none shrink-0 text-muted-foreground forced-colors:text-[CanvasText]"
    >
      <path d={up ? 'm2 6.5 3-3 3 3' : 'm2 3.5 3 3 3-3'} stroke="currentColor" strokeWidth="1.5" />
    </svg>
  );
}

export function SelectGroup({ className, ...props }: SelectPrimitive.Group.Props) {
  return (
    <SelectPrimitive.Group data-slot="select-group" className={cn('p-1', className)} {...props} />
  );
}

export function SelectValue({ className, ...props }: SelectPrimitive.Value.Props) {
  return (
    <SelectPrimitive.Value
      data-slot="select-value"
      className={cn('block min-w-0 flex-1 truncate text-start', className)}
      {...props}
    />
  );
}

export function SelectTrigger({ className, children, ...props }: SelectPrimitive.Trigger.Props) {
  return (
    <SelectPrimitive.Trigger
      data-slot="select-trigger"
      className={cn(
        fieldBase,
        'flex w-full items-center justify-between gap-2 bg-muted text-foreground px-[8px] py-[6.4px] leading-[1.55] cursor-pointer disabled:opacity-50',
        className,
      )}
      {...props}
    >
      {children}
      <SelectPrimitive.Icon data-slot="select-icon">
        <Chevron />
      </SelectPrimitive.Icon>
    </SelectPrimitive.Trigger>
  );
}

export function SelectContent({
  className,
  children,
  side = 'bottom',
  sideOffset = 4,
  align = 'start',
  alignOffset = 0,
  alignItemWithTrigger = false,
  ...props
}: SelectPrimitive.Popup.Props &
  Pick<
    SelectPrimitive.Positioner.Props,
    'align' | 'alignOffset' | 'side' | 'sideOffset' | 'alignItemWithTrigger'
  >) {
  return (
    <SelectPrimitive.Portal>
      <SelectPrimitive.Positioner
        data-slot="select-positioner"
        side={side}
        sideOffset={sideOffset}
        align={align}
        alignOffset={alignOffset}
        alignItemWithTrigger={alignItemWithTrigger}
        collisionPadding={8}
        collisionAvoidance={{ side: 'flip', align: 'shift', fallbackAxisSide: 'none' }}
        className="isolate z-[50] max-w-[calc(100vw-16px)]"
      >
        <SelectPrimitive.Popup
          data-slot="select-content"
          data-align-trigger={alignItemWithTrigger}
          className={cn(
            'box-border w-[var(--anchor-width)] min-w-0 max-w-full max-h-[min(24rem,var(--available-height))] relative overflow-hidden rounded-control border border-solid border-input bg-popover text-popover-foreground text-body [font-family:var(--sans)] font-normal leading-[1.55] shadow-[var(--e-pop)] outline-none',
            className,
          )}
          {...props}
        >
          <SelectScrollUpButton />
          <SelectPrimitive.List className="max-h-[calc(min(24rem,var(--available-height))-2px)] overflow-y-auto">
            {children}
          </SelectPrimitive.List>
          <SelectScrollDownButton />
        </SelectPrimitive.Popup>
      </SelectPrimitive.Positioner>
    </SelectPrimitive.Portal>
  );
}

export function SelectLabel({ className, ...props }: SelectPrimitive.GroupLabel.Props) {
  return (
    <SelectPrimitive.GroupLabel
      data-slot="select-label"
      className={cn('px-2 py-1 text-label text-muted-foreground', className)}
      {...props}
    />
  );
}

export function SelectItem({ className, children, ...props }: SelectPrimitive.Item.Props) {
  return (
    <SelectPrimitive.Item
      data-slot="select-item"
      data-value={typeof props.value === 'string' ? props.value : undefined}
      title={typeof children === 'string' ? children : undefined}
      className={cn(
        'relative box-border flex w-full min-h-[44px] cursor-pointer items-center rounded-control ps-[8px] pe-[28px] py-[8px] text-body text-foreground outline-none data-[highlighted]:bg-accent data-[highlighted]:text-accent-foreground data-[disabled]:cursor-default data-[disabled]:text-muted-foreground',
        className,
      )}
      {...props}
    >
      <SelectPrimitive.ItemText className="min-w-0 flex-1 line-clamp-2 whitespace-normal [overflow-wrap:anywhere]">
        {children}
      </SelectPrimitive.ItemText>
      <SelectPrimitive.ItemIndicator className="pointer-events-none absolute end-[8px] flex items-center justify-center">
        <svg aria-hidden="true" viewBox="0 0 12 12" width="12" height="12" fill="none">
          <path d="m2 6 2.5 2.5L10 3" stroke="currentColor" strokeWidth="1.5" />
        </svg>
      </SelectPrimitive.ItemIndicator>
    </SelectPrimitive.Item>
  );
}

export function SelectSeparator({ className, ...props }: SelectPrimitive.Separator.Props) {
  return (
    <SelectPrimitive.Separator
      data-slot="select-separator"
      className={cn('pointer-events-none my-1 h-px bg-border', className)}
      {...props}
    />
  );
}

export function SelectScrollUpButton({
  className,
  ...props
}: ComponentProps<typeof SelectPrimitive.ScrollUpArrow>) {
  return (
    <SelectPrimitive.ScrollUpArrow
      data-slot="select-scroll-up-button"
      className={cn(
        'top-0 z-[1] flex w-full items-center justify-center bg-popover py-2',
        className,
      )}
      {...props}
    >
      <Chevron up />
    </SelectPrimitive.ScrollUpArrow>
  );
}
export function SelectScrollDownButton({
  className,
  ...props
}: ComponentProps<typeof SelectPrimitive.ScrollDownArrow>) {
  return (
    <SelectPrimitive.ScrollDownArrow
      data-slot="select-scroll-down-button"
      className={cn(
        'bottom-0 z-[1] flex w-full items-center justify-center bg-popover py-2',
        className,
      )}
      {...props}
    >
      <Chevron />
    </SelectPrimitive.ScrollDownArrow>
  );
}
