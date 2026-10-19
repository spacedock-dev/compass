/* shadcn Card, Base UI flavour. CLI: shadcn@4.21.4.
   Registry: https://ui.shadcn.com/r/styles/base-nova/card.json
   Upstream content SHA-256: 645c3d73e387a99f1492220cc619453b0c7f5454134ee3cd548be7a80f7eccde
   MIT; the full upstream notice ships in react-licenses.txt.
   Display recipes preserve the measured cascade; docs/design-shadcn-adoption.md. */
import type { ComponentProps } from 'react';
import { cva, type VariantProps } from 'class-variance-authority';
import { cn } from '@/lib/utils';

const cardVariants = cva('min-w-0', {
  variants: {
    variant: {
      'session-row':
        'grid w-full p-0 text-foreground [border-bottom:1px_solid_var(--line)] hover:bg-card [@media(max-width:620px)]:[border:1px_solid_var(--line)] [@media(max-width:620px)]:rounded-control [@media(max-width:620px)]:bg-card',
      'session-current':
        'block px-[17px] py-[14px] border border-solid border-[var(--rule)] border-l-2 border-l-border rounded-card bg-card',
      'session-ask':
        'block px-[16px] py-[13px] border border-solid border-[var(--rule)] border-l-2 border-l-[var(--amber)] rounded-card bg-card',
      'session-landed': 'flex flex-col gap-[4px] pl-[9px] [border-left:1px_solid_var(--rule)]',
      'intent-row': 'flex flex-col gap-[3px] pl-[9px] [border-left:1px_solid_var(--rule)]',
      'intent-panel':
        'flex flex-col gap-[6px] p-0 min-[761px]:gap-[14px] min-[761px]:p-[16px] min-[761px]:border min-[761px]:border-solid min-[761px]:border-[var(--rule)] min-[761px]:rounded-card min-[761px]:bg-card',
      'drift-panel':
        'block m-0 pt-0 px-0 pb-[4px] border border-solid border-[var(--rule)] rounded-card bg-card',
      'reading-job':
        'flex flex-col [gap:var(--sp-3)] [padding:var(--sp-4)] bg-card rounded-card max-w-[var(--measure)]',
      'reading-notice':
        'flex flex-col [gap:var(--sp-3)] [padding:var(--sp-4)] bg-card border border-solid border-border rounded-card max-w-[var(--measure)]',
      'reading-stale':
        'flex flex-col gap-[6px] px-[12px] py-[10px] border border-solid border-[var(--amber)] rounded-control',
      'steer-box': 'flex flex-col gap-[8px]',
      'steer-receipt': 'block p-[10px] [border-left:2px_solid_var(--amber)] bg-card',
      'project-row':
        'grid w-full px-[18px] py-[16px] border border-solid border-border border-l-2 border-l-[var(--project-tone)] rounded-card bg-card hover:[border-color:var(--line-hi)] hover:[border-left-color:var(--project-tone)] focus-within:[border-color:var(--line-hi)] focus-within:[border-left-color:var(--project-tone)] [&.next-project-row--history]:py-[12px] [&.next-project-row--history]:border-l [&.next-project-row--history]:border-l-border [&.next-project-row--history]:bg-transparent',
      'project-goal':
        'flex flex-col gap-[9px] px-0 py-[10px] [border-right:0] [border-bottom:0] [border-left:0] [border-top:1px_solid_var(--rule)] rounded-none bg-transparent',
      'project-recovery': 'grid [border-bottom:1px_solid_var(--rule)]',
      'course-row': 'block px-0 py-[13px] [border-bottom:1px_solid_var(--rule)]',
      'stage-rule': 'block p-4 [border:1px_solid_var(--rule)] rounded-card',
      'rail-panel':
        'flex flex-col gap-[12px] px-[22px] py-[18px] [border-bottom:1px_solid_var(--rule)] first:pt-[20px] last:[border-bottom:0]',
      'rail-wait':
        'flex flex-col gap-[8px] px-[13px] py-[12px] border border-solid border-[var(--rule)] border-l-2 border-l-[var(--amber)] rounded-card bg-card',
      'timeline-details':
        'grid gap-[7px] px-[12px] py-[10px] [border-left:2px_solid_var(--rule)] bg-[var(--sunk)] text-muted-foreground [font-family:var(--sans)] text-body font-medium leading-[1.55]',
      'terminal-frame':
        'flex flex-col [border:1px_solid_var(--rule)] rounded-card bg-[var(--sunk)] text-foreground overflow-hidden [font-family:var(--sans)] text-body leading-[1.5]',
      'attention-brief':
        'grid gap-[10px] px-[18px] py-[16px] border border-solid border-[var(--rule)] border-l-2 border-l-[var(--accent-dim)] rounded-card bg-card',
      'attention-item':
        'grid px-[18px] py-[14px] border border-solid border-[var(--rule)] border-l-2 border-l-border rounded-card bg-card [&.next-attention-item--board]:bg-transparent',
      'capacity-band':
        'grid px-[4px] py-[13px] [border-bottom:1px_solid_var(--line)] hover:bg-card [@media(max-width:980px)]:py-[15px]',
      'capacity-prospect':
        'block px-[18px] py-[15px] [border-left:2px_solid_var(--accent-dim)] [border-radius:0_var(--r-card)_var(--r-card)_0] bg-card text-muted-foreground text-body leading-[1.6]',
      'quota-consent':
        'block px-[18px] py-[16px] [border-left:3px_solid_var(--amber)] bg-card text-body leading-[1.5] [.next-project-detail-rail_&]:p-[12px] [.next-project-detail-rail_&]:text-label',
      'observer-controls':
        'block px-[18px] py-[16px] [border-left:3px_solid_var(--amber)] bg-card text-body leading-[1.5] [.next-project-detail-rail_&]:p-[12px] [.next-project-detail-rail_&]:text-label',
      'work-panel': 'flex flex-col gap-[8px] pt-[12px] px-[16px] pb-[14px]',
    },
    tone: {
      unknown: '',
      want: 'border-l-[var(--amber)]',
      bad: 'border-l-[var(--clay)]',
      ok: 'border-l-[var(--accent)]',
    },
  },
  defaultVariants: { variant: 'session-current', tone: 'unknown' },
});
function Card({
  className,
  variant,
  tone,
  as: Tag = 'div',
  ...props
}: ComponentProps<'div'> &
  VariantProps<typeof cardVariants> & { readonly as?: 'div' | 'section' | 'article' | 'aside' }) {
  return (
    <Tag
      data-slot="card"
      data-variant={variant ?? 'session-current'}
      className={cn(cardVariants({ variant, tone }), className)}
      {...props}
    />
  );
}
export { Card, cardVariants };
