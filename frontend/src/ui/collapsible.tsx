/* shadcn Collapsible, Base UI flavour. CLI: shadcn@4.21.4.
   Registry: https://ui.shadcn.com/r/styles/base-nova/collapsible.json
   Upstream content SHA-256: ead4349ff7b01d696ef89294a81d18ee1d3f732321398896462c834ab9b9e065
   MIT; the full upstream notice ships in react-licenses.txt.
   Native surface chrome stays in legacy; panel motion uses the existing tokens.
   docs/design-shadcn-adoption.md#accordion-and-collapsible-layer owns the tuning. */
import type { ReactNode } from 'react';
import { Collapsible as CollapsiblePrimitive } from '@base-ui/react/collapsible';
import { cn } from '../lib/utils';
import { disclosureMotion, disclosurePanelMeasure, disclosureTrigger } from './accordion';
import { DisclosureChevron } from './disclosureChevron';

export function Collapsible(props: CollapsiblePrimitive.Root.Props) {
  return <CollapsiblePrimitive.Root data-slot="collapsible" {...props} />;
}
export function CollapsibleTrigger({
  className,
  children,
  chevron = <DisclosureChevron />,
  ...props
}: CollapsiblePrimitive.Trigger.Props & { readonly chevron?: ReactNode }) {
  return (
    <CollapsiblePrimitive.Trigger
      data-slot="collapsible-trigger"
      className={cn(disclosureTrigger, className)}
      {...props}
    >
      {children}
      {chevron}
    </CollapsiblePrimitive.Trigger>
  );
}
export function CollapsibleContent({ className, ...props }: CollapsiblePrimitive.Panel.Props) {
  return (
    <CollapsiblePrimitive.Panel
      data-slot="collapsible-content"
      className={cn(
        disclosureMotion,
        disclosurePanelMeasure,
        'h-[var(--collapsible-panel-height)]',
        className,
      )}
      {...props}
    />
  );
}
