/* shadcn textarea, Base UI flavour. CLI: shadcn@4.21.4.
   Registry: https://ui.shadcn.com/r/styles/base-nova/textarea.json
   Upstream content SHA-256: 82601c91ffc6c727d924162c78d7cb853114bcced4e2eb922a68ca12d4239c0f
   MIT; the full upstream notice ships in react-licenses.txt.
   Content-driven sizing is removed so field memory can restore a dragged height.
   docs/design-shadcn-adoption.md#form-controls-layer owns the tuning. */
import type { ComponentProps } from 'react';
import { cn } from '../lib/utils';
import { fieldBase } from './input';

export type TextareaProps = ComponentProps<'textarea'> & {
  appearance?: 'intent' | 'memo' | 'draft' | 'correction';
};

const surfaces = {
  intent:
    'min-h-[56px] p-[7px] bg-background text-[var(--ink-value)] leading-[1.55] in-[[data-next-cockpit-drafted]]:bg-muted in-[.next-cockpit-held-line]:min-h-[44px]',
  memo: 'min-h-[5rem] p-[8px] bg-background text-foreground leading-[1.5]',
  draft: 'p-[8px] bg-background text-foreground leading-[1.5]',
  correction: 'min-h-[120px] p-[7px] bg-background text-[var(--ink-value)] leading-[1.55]',
};

export function Textarea({ className, appearance = 'intent', ...props }: TextareaProps) {
  return (
    <textarea
      data-slot="textarea"
      className={cn(fieldBase, 'block w-full resize-y', surfaces[appearance], className)}
      {...props}
    />
  );
}
