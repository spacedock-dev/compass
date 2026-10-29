/* shadcn Radio Group, Base UI flavour. CLI: shadcn@4.21.4.
   Registry: https://ui.shadcn.com/r/styles/base-nova/radio-group.json
   Upstream content SHA-256: f779542f2370b82fcbb91278fb94f7ad4af59d0f36512633492604b27da48e8d
   MIT; the full upstream notice ships in react-licenses.txt.
   Deviations: local cn, page radius tokens and outline focus, no dark: or field-group variants. The dot
   stays 16px; the row label around it is the 44px target.
   docs/plans/2026-10-29-sessions-search.md#7-shadcn-components owns the adoption until its layer is recorded. */
import { Radio as RadioPrimitive } from '@base-ui/react/radio';
import { RadioGroup as RadioGroupPrimitive } from '@base-ui/react/radio-group';
import { cn } from '../lib/utils';

function RadioGroup({ className, ...props }: RadioGroupPrimitive.Props) {
  return (
    <RadioGroupPrimitive
      data-slot="radio-group"
      className={cn('grid w-full gap-0', className)}
      {...props}
    />
  );
}

function RadioGroupItem({ className, ...props }: RadioPrimitive.Root.Props) {
  return (
    <RadioPrimitive.Root
      data-slot="radio-group-item"
      className={cn(
        'group/radio-group-item peer relative flex aspect-square size-4 shrink-0 rounded-pill border border-solid border-input bg-background outline-none after:absolute after:-inset-x-3 after:-inset-y-2 focus-visible:outline-2 focus-visible:outline-solid focus-visible:outline-ring focus-visible:outline-offset-2 data-[disabled]:cursor-not-allowed data-[disabled]:opacity-50 aria-invalid:border-destructive data-checked:border-primary data-checked:bg-primary data-checked:text-primary-foreground',
        className,
      )}
      {...props}
    >
      <RadioPrimitive.Indicator
        data-slot="radio-group-indicator"
        className="flex size-4 items-center justify-center"
      >
        <span className="absolute top-1/2 left-1/2 size-2 -translate-x-1/2 -translate-y-1/2 rounded-pill bg-primary-foreground" />
      </RadioPrimitive.Indicator>
    </RadioPrimitive.Root>
  );
}

export { RadioGroup, RadioGroupItem };
