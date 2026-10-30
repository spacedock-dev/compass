/* shadcn Accordion, Base UI flavour. CLI: shadcn@4.21.4.
   Registry: https://ui.shadcn.com/r/styles/base-nova/accordion.json
   Upstream content SHA-256: ad36d3b4996e7ca212175c5f9e0f5b19f8dc737572a0ca1a685ebd4193ed8351
   MIT; the full upstream notice ships in react-licenses.txt.
   Native surface chrome stays in legacy; panel motion uses the existing tokens.
   docs/design-shadcn-adoption.md#accordion-and-collapsible-layer owns the tuning. */
import { Accordion as AccordionPrimitive } from '@base-ui/react/accordion';
import { cn } from '../lib/utils';
import { DisclosureChevron } from './disclosureChevron';

export const disclosureTrigger =
  'min-h-[44px] min-w-[44px] max-w-full text-start focus-visible:outline-2 focus-visible:outline-solid focus-visible:outline-[var(--accent)] focus-visible:outline-offset-2';
export const disclosureMotion =
  'overflow-clip [overflow-clip-margin:6px] opacity-100 transition-[height,opacity] duration-[var(--disclose-dur)] ease-[var(--disclose-ease)] data-[starting-style]:h-0 data-[starting-style]:opacity-0 data-[ending-style]:h-0 data-[ending-style]:opacity-0 motion-reduce:transition-none motion-reduce:h-auto motion-reduce:data-[starting-style]:h-auto motion-reduce:data-[ending-style]:h-auto motion-reduce:data-[starting-style]:opacity-100 motion-reduce:data-[ending-style]:opacity-100';

export function Accordion({ className, ...props }: AccordionPrimitive.Root.Props) {
  return <AccordionPrimitive.Root data-slot="accordion" className={className} {...props} />;
}
export function AccordionItem(props: AccordionPrimitive.Item.Props) {
  return <AccordionPrimitive.Item data-slot="accordion-item" {...props} />;
}
export function AccordionTrigger({
  className,
  children,
  headerProps,
  ...props
}: AccordionPrimitive.Trigger.Props & { readonly headerProps?: AccordionPrimitive.Header.Props }) {
  return (
    <AccordionPrimitive.Header render={<div />} {...headerProps}>
      <AccordionPrimitive.Trigger
        data-slot="accordion-trigger"
        className={cn(disclosureTrigger, className)}
        {...props}
      >
        {children}
        <DisclosureChevron />
      </AccordionPrimitive.Trigger>
    </AccordionPrimitive.Header>
  );
}
export function AccordionContent({ className, ...props }: AccordionPrimitive.Panel.Props) {
  return (
    <AccordionPrimitive.Panel
      data-slot="accordion-content"
      className={cn(disclosureMotion, 'h-[var(--accordion-panel-height)]', className)}
      {...props}
    />
  );
}
