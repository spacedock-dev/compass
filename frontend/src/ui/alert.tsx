/* shadcn Alert, Base UI flavour. CLI: shadcn@4.21.4.
   Registry: https://ui.shadcn.com/r/styles/base-nova/alert.json
   Upstream content SHA-256: f253568242c1c69b343f12474002fdbe229f603158171c59e21c491ab79f2e6e
   MIT; the full upstream notice ships in react-licenses.txt.
   Display recipes preserve the measured cascade; docs/design-shadcn-adoption.md. */
import type { ComponentProps } from 'react';
import { cva, type VariantProps } from 'class-variance-authority';
import { cn } from '@/lib/utils';

const notice =
  'm-0 rounded-standard-card border border-solid border-[var(--rule)] px-4 py-3 text-body text-foreground';

const alertVariants = cva('block', {
  variants: {
    variant: {
      notice: cn(notice, 'bg-[var(--status-ended-bg)]'),
      warning: cn(notice, 'bg-[var(--status-waiting-bg)]'),
      danger: cn(notice, 'bg-danger-tint'),
      'session-health':
        'px-[16px] py-[14px] [border-left:3px_solid_var(--amber)] bg-card text-muted-foreground text-body leading-[1.5]',
      'observer-status': 'm-0',
      'answer-failure': 'p-0 text-foreground text-label leading-[normal]',
      'intent-note':
        'm-0 max-w-[var(--measure)] text-muted-foreground [font-family:var(--sans)] text-body font-medium leading-[1.55]',
      'shell-notice':
        'flex flex-wrap items-center gap-[10px] px-[12px] py-[10px] [border-left:3px_solid_var(--clay)] bg-card text-muted-foreground text-body font-medium leading-[1.55] [&[data-next-state=history-reset]]:border-l-[var(--ink2)] [&[data-next-state=build-changed]]:border-l-[var(--ink2)]',
      'terminal-absence': 'pt-[4px] px-0 pb-[10px] max-w-[70ch]',
      'timeline-stale':
        'max-w-[var(--measure)] text-muted-foreground [font-family:var(--sans)] text-body font-normal leading-[1.55]',
      'drift-nudge':
        'px-[12px] py-[10px] border border-solid border-[var(--amber)] rounded-control text-foreground text-body leading-[1.5]',
      'reading-cap':
        'sticky top-0 z-20 flex min-h-8 items-center px-[12px] py-[6px] [border-left:3px_solid_var(--clay)] bg-card text-foreground text-body font-medium leading-[1.4] shadow-[0_1px_0_var(--rule)]',
    },
  },
  defaultVariants: { variant: 'answer-failure' },
});
function Alert({
  className,
  variant,
  as: Tag = 'div',
  role = 'status',
  announce = true,
  ...props
}: ComponentProps<'div'> &
  VariantProps<typeof alertVariants> & {
    readonly as?: 'div' | 'aside' | 'p';
    readonly announce?: boolean;
  }) {
  return (
    <Tag
      data-slot="alert"
      data-variant={variant ?? 'answer-failure'}
      role={announce ? role : undefined}
      className={cn(alertVariants({ variant }), className)}
      {...props}
    />
  );
}
export { Alert, alertVariants };
