/* shadcn Tooltip, Base UI flavour. CLI: shadcn@4.21.4.
   Registry: https://ui.shadcn.com/r/styles/base-nova/tooltip.json
   Upstream content SHA-256: f83d5f511812573f4ac98b866d397a46fda0f27eeb0af0ea89af01969eefbc5a
   MIT; the full upstream notice ships in react-licenses.txt.
   Deviations: local cn, the page's popup chrome (the popover's surface, line and shadow) in place of the
   registry's inverted pill, no arrow, no animation classes (the page owns its motion tokens), and a
   bounded width and an explicit tooltip role (the pinned Base UI popup supplies none). A tooltip never carries the only copy of a fact: the trigger names the same words to a
   screen reader, and a legend states them where hover does not exist.
   docs/design-shadcn-adoption.md#icons-and-tooltips owns the decision. */
import { Tooltip as TooltipPrimitive } from '@base-ui/react/tooltip';
import { cn } from '../lib/utils';

export function TooltipProvider({ delay = 250, ...props }: TooltipPrimitive.Provider.Props) {
  return <TooltipPrimitive.Provider data-slot="tooltip-provider" delay={delay} {...props} />;
}

export function Tooltip(props: TooltipPrimitive.Root.Props) {
  return <TooltipPrimitive.Root data-slot="tooltip" {...props} />;
}

export function TooltipTrigger(props: TooltipPrimitive.Trigger.Props) {
  return <TooltipPrimitive.Trigger data-slot="tooltip-trigger" {...props} />;
}

export function TooltipContent({
  className,
  side = 'top',
  sideOffset = 6,
  align = 'center',
  alignOffset = 0,
  children,
  ...props
}: TooltipPrimitive.Popup.Props &
  Pick<TooltipPrimitive.Positioner.Props, 'align' | 'alignOffset' | 'side' | 'sideOffset'>) {
  return (
    <TooltipPrimitive.Portal>
      <TooltipPrimitive.Positioner
        data-slot="tooltip-positioner"
        align={align}
        alignOffset={alignOffset}
        side={side}
        sideOffset={sideOffset}
        collisionPadding={16}
        className="isolate z-[4] max-w-[calc(100vw-32px)]"
      >
        <TooltipPrimitive.Popup
          data-slot="tooltip-content"
          role="tooltip"
          className={cn(
            'box-border w-fit max-w-[min(20rem,calc(100vw-32px))] [overflow-wrap:anywhere] rounded-control border border-solid border-[var(--line)] bg-[var(--raise)] px-2.5 py-1.5 text-label text-foreground shadow-[var(--e-pop)] opacity-100 transition-opacity duration-[var(--disclose-pop-dur)] ease-[var(--disclose-ease)] data-[starting-style]:opacity-0 data-[ending-style]:opacity-0 motion-reduce:transition-none',
            className,
          )}
          {...props}
        >
          {children}
        </TooltipPrimitive.Popup>
      </TooltipPrimitive.Positioner>
    </TooltipPrimitive.Portal>
  );
}
