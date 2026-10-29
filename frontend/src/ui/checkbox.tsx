/* shadcn Checkbox, Base UI flavour. CLI: shadcn@4.21.4.
   Registry: https://ui.shadcn.com/r/styles/base-nova/checkbox.json
   Upstream content SHA-256: 0cc30ddee3fa93818799f48ad47a58a30652c956ce940373c3feb3559167f0af
   MIT; the full upstream notice ships in react-licenses.txt.
   Deviations: local cn, the page's check icon, page radius and outline focus, no dark: or field-group
   variants. The box stays 16px; the row label around it is the 44px target.
   docs/design-shadcn-adoption.md#checkbox-and-radio-group-layer owns the tuning. */
import { Checkbox as CheckboxPrimitive } from '@base-ui/react/checkbox';
import { cn } from '../lib/utils';
import { Icon } from './icons';

function Checkbox({ className, ...props }: CheckboxPrimitive.Root.Props) {
  return (
    <CheckboxPrimitive.Root
      data-slot="checkbox"
      className={cn(
        'peer relative flex size-4 shrink-0 items-center justify-center rounded-control border border-solid border-input bg-background transition-colors outline-none after:absolute after:-inset-x-3 after:-inset-y-2 focus-visible:outline-2 focus-visible:outline-solid focus-visible:outline-ring focus-visible:outline-offset-2 data-[disabled]:cursor-not-allowed data-[disabled]:opacity-50 aria-invalid:border-destructive data-checked:border-primary data-checked:bg-primary data-checked:text-primary-foreground',
        className,
      )}
      {...props}
    >
      <CheckboxPrimitive.Indicator
        data-slot="checkbox-indicator"
        className="grid place-content-center text-current transition-none [&>svg]:size-3.5"
      >
        <Icon name="check" />
      </CheckboxPrimitive.Indicator>
    </CheckboxPrimitive.Root>
  );
}

export { Checkbox };
