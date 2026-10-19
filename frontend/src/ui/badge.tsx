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
      'session-state':
        'inline-block m-0 px-[8px] py-[2px] border border-solid border-border rounded-pill text-muted-foreground [font-family:var(--mono)] text-label font-normal leading-[normal]',
      'drift-pill':
        'inline-flex items-center gap-[8px] max-w-full px-[10px] py-[3px] border border-solid border-border rounded-pill text-foreground text-label',
      'course-tag':
        'text-[var(--ink-label)] [font-family:var(--mono)] text-label font-semibold leading-[normal] tracking-[.07em]',
      'notify-blocked': 'text-foreground',
      'terminal-tag': 'ml-auto text-muted-foreground',
      'work-flag':
        'ml-auto px-[7px] py-0 border border-solid border-[var(--rule)] rounded-pill text-muted-foreground [font-family:var(--mono)] text-label font-medium leading-[1.5] [&+[data-variant=work-flag]]:ml-0',
    },
  },
  defaultVariants: { variant: 'session-state' },
});

function Badge({
  className,
  variant = 'session-state',
  render,
  ...props
}: useRender.ComponentProps<'span'> & VariantProps<typeof badgeVariants>) {
  return useRender({
    defaultTagName: 'span',
    props: mergeProps<'span'>({ className: cn(badgeVariants({ variant }), className) }, props),
    render,
    state: { slot: 'badge', variant },
  });
}
export { Badge, badgeVariants };
