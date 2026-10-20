/* shadcn input, Base UI flavour. CLI: shadcn@4.21.4.
   Registry: https://ui.shadcn.com/r/styles/base-nova/input.json
   Upstream content SHA-256: dab990dfefa0ba78854ab6602ad074270dba9d7d1262184d9bfbb62bd990903b
   MIT; the full upstream notice ships in react-licenses.txt.
   The native node stays uncontrolled; only the registry chrome is adopted.
   docs/design-shadcn-adoption.md#form-controls-layer owns the tuning. */
import type { ComponentProps } from 'react';
import { cn } from '../lib/utils';

export const fieldBase =
  'box-border min-h-[44px] min-w-0 max-w-full border border-input rounded-control text-body [font-family:var(--sans)] font-normal [text-align:start] focus-visible:outline-2 focus-visible:outline-solid focus-visible:outline-ring focus-visible:outline-offset-[2px] disabled:cursor-not-allowed aria-invalid:border-destructive';

export function Input({ className, type, ...props }: ComponentProps<'input'>) {
  return (
    <input
      type={type}
      data-slot="input"
      className={cn(
        fieldBase,
        'inline-block w-full bg-background text-foreground p-[8px] leading-[1.55]',
        className,
      )}
      {...props}
    />
  );
}
