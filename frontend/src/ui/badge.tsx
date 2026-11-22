/* shadcn Badge, Base UI flavour. CLI: shadcn@4.21.4.
   Registry: https://ui.shadcn.com/r/styles/base-nova/badge.json
   Upstream content SHA-256: d9fb280e266119c4b62a4c518e63152de27b094c68d3e5f8929d05bfb0c1bc6c
   MIT; the full upstream notice ships in react-licenses.txt.
   Display recipes preserve the measured cascade; docs/design-shadcn-adoption.md. */
import { mergeProps } from '@base-ui/react/merge-props';
import { useRender } from '@base-ui/react/use-render';
import { cva, type VariantProps } from 'class-variance-authority';
import { cn } from '@/lib/utils';

const badgeVariants = cva('', {
  variants: {
    variant: {
      status:
        'inline-block px-2 py-0.5 border border-solid border-border rounded-pill [font-family:var(--sans)] text-label font-medium text-muted-foreground',
      progress:
        'inline-block max-w-full whitespace-nowrap px-2.5 py-0.5 border border-solid rounded-pill [font-family:var(--sans)] text-label font-semibold',
      'count-chip':
        'inline-block px-1.5 border border-solid border-border rounded-pill [font-family:var(--sans)] text-label font-medium text-muted-foreground',
      'drift-pill':
        'inline-flex items-center gap-[8px] max-w-full px-[10px] py-[3px] border border-solid border-border rounded-pill text-foreground text-label',
      'course-tag':
        'text-[var(--ink-label)] [font-family:var(--mono)] text-label font-semibold leading-[normal] tracking-[.07em]',
      'notify-blocked': 'text-foreground',
      'terminal-tag': 'ml-auto text-muted-foreground',
      'work-flag':
        'ml-auto px-[7px] py-0 border border-solid border-[var(--rule)] rounded-pill text-muted-foreground [font-family:var(--mono)] text-label font-medium leading-[1.5] [&+[data-variant=work-flag]]:ml-0',
    },
    tone: {
      medium: 'border-[var(--progress-slightly-off-course)] text-[var(--clay)]',
      high: 'border-[var(--progress-off-course)] bg-[var(--progress-off-course)] text-[var(--on-accent)]',
      extreme:
        'border-[var(--progress-way-off-course)] bg-[var(--progress-way-off-course)] text-[var(--on-accent)]',
    },
  },
  defaultVariants: { variant: 'status' },
});

function Badge({
  className,
  variant = 'status',
  tone,
  render,
  ...props
}: useRender.ComponentProps<'span'> & VariantProps<typeof badgeVariants>) {
  return useRender({
    defaultTagName: 'span',
    props: mergeProps<'span'>(
      { className: cn(badgeVariants({ variant, tone }), className) },
      props,
    ),
    render,
    state: { slot: 'badge', variant },
  });
}
export { Badge, badgeVariants };
