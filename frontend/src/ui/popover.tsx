/* shadcn Popover, Base UI flavour. CLI: shadcn@4.21.4.
   Registry: https://ui.shadcn.com/r/styles/base-nova/popover.json
   Upstream content SHA-256: b6bc5045e7b67414816f813788b5f699d0cc5e4a23debe76c89a6ddb68079c26
   MIT; the full upstream notice ships in react-licenses.txt.
   docs/design-shadcn-adoption.md#popover-layer owns the focus, portal and chrome tuning. */
import { Popover as PopoverPrimitive } from '@base-ui/react/popover';
import { cn } from '../lib/utils';
import { disclosureTrigger } from './accordion';
import { DisclosureChevron } from './disclosureChevron';

export function Popover(props: PopoverPrimitive.Root.Props) {
  return <PopoverPrimitive.Root {...props} />;
}

export function PopoverTrigger({ className, children, ...props }: PopoverPrimitive.Trigger.Props) {
  return (
    <PopoverPrimitive.Trigger
      data-slot="popover-trigger"
      className={cn(disclosureTrigger, className)}
      {...props}
    >
      {children}
      <DisclosureChevron />
    </PopoverPrimitive.Trigger>
  );
}

export function PopoverContent({
  className,
  container,
  align = 'end',
  alignOffset = 0,
  side = 'bottom',
  sideOffset = 4,
  collisionAvoidance,
  ...props
}: PopoverPrimitive.Popup.Props &
  Pick<
    PopoverPrimitive.Positioner.Props,
    'align' | 'alignOffset' | 'side' | 'sideOffset' | 'collisionAvoidance'
  > &
  Pick<PopoverPrimitive.Portal.Props, 'container'>) {
  return (
    <PopoverPrimitive.Portal container={container} keepMounted>
      <PopoverPrimitive.Positioner
        data-slot="popover-positioner"
        align={align}
        alignOffset={alignOffset}
        side={side}
        sideOffset={sideOffset}
        {...(collisionAvoidance ? { collisionAvoidance } : {})}
        collisionPadding={16}
        className="isolate z-[3] max-w-[calc(100vw-32px)]"
      >
        <PopoverPrimitive.Popup
          data-slot="popover-content"
          className={cn(
            'box-border min-w-0 w-[min(var(--measure),calc(100vw-32px))] max-w-full max-h-[var(--available-height)] overflow-y-auto [overflow-wrap:anywhere] rounded-control border border-solid border-[var(--line)] bg-[var(--raise)] px-3 py-[10px] text-body text-foreground text-start shadow-[0_18px_44px_-22px_#000] outline-none opacity-100 transition-opacity duration-[var(--disclose-pop-dur)] ease-[var(--disclose-ease)] data-[starting-style]:opacity-0 data-[ending-style]:opacity-0 motion-reduce:transition-none motion-reduce:data-[starting-style]:opacity-100 motion-reduce:data-[ending-style]:opacity-100',
            className,
          )}
          {...props}
        />
      </PopoverPrimitive.Positioner>
    </PopoverPrimitive.Portal>
  );
}
