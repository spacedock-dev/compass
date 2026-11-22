/* shadcn Switch, Base UI flavour. CLI: shadcn@4.21.4.
   Registry: https://ui.shadcn.com/r/styles/base-nova/switch.json
   Upstream content SHA-256: d232e2ffcfa122c59099872bcb8395eaad36d42fa9d2e0e40382ad19994065e2
   MIT. The full upstream notice ships in react-licenses.txt.
   Uses local cn and a native button for the focus lane. A separate track lets the 44px target
   keep the shared focus outline. One size, with Compass tokens for both states.
   docs/design-shadcn-adoption.md#switch-layer owns the tuning. */
import { Switch as SwitchPrimitive } from '@base-ui/react/switch';
import type { ComponentProps } from 'react';
import { cn } from '@/lib/utils';

type SwitchProps = Omit<
  ComponentProps<typeof SwitchPrimitive.Root>,
  'className' | 'nativeButton' | 'render'
> & {
  readonly className?: string;
};

function Switch({ children, className, ...props }: SwitchProps) {
  return (
    <SwitchPrimitive.Root
      nativeButton
      render={<button type="button" />}
      data-slot="switch"
      className={cn(
        'group/switch inline-flex min-h-[44px] min-w-[44px] box-border items-center justify-center border-0 bg-transparent p-0 cursor-pointer focus-visible:outline-2 focus-visible:outline-solid focus-visible:outline-ring focus-visible:outline-offset-2 disabled:cursor-not-allowed aria-disabled:cursor-not-allowed',
        className,
      )}
      {...props}
    >
      {children}
      <span
        aria-hidden="true"
        data-slot="switch-track"
        className="flex h-[30px] w-[52px] shrink-0 box-border items-center rounded-full border border-solid border-input bg-[var(--sunk)] p-0.5 group-data-checked/switch:border-[var(--accent-dim)] group-data-checked/switch:bg-[var(--accent-dim)]"
      >
        <SwitchPrimitive.Thumb
          data-slot="switch-thumb"
          className="size-[24px] shrink-0 rounded-full bg-[var(--ink2)] data-checked:ms-auto data-checked:bg-[var(--on-accent)]"
        />
      </span>
    </SwitchPrimitive.Root>
  );
}

export { Switch };
