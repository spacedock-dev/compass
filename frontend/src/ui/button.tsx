/* shadcn Button, Base UI flavour. CLI: shadcn@4.21.4.
   Registry: https://ui.shadcn.com/r/styles/base-nova/button.json
   Upstream content SHA-256: 313353436d0fcc8e44ab470adb614b9fd013d28626f624328ea0d66d41a6c81b
   MIT; the full upstream notice ships in react-licenses.txt.
   Tuned to the existing control scale; docs/design-shadcn-adoption.md owns the adoption rules. */
import { Button as ButtonPrimitive } from '@base-ui/react/button';
import { cva, type VariantProps } from 'class-variance-authority';
import type { ComponentProps, ReactNode } from 'react';
import { cn } from '../lib/utils';

const action =
  'inline-flex items-center justify-center rounded-control border border-solid border-[var(--line)] bg-transparent text-foreground font-[family-name:var(--sans)] text-body leading-[1.55] px-3.5 py-[.5625rem] cursor-pointer hover:border-[var(--line-hi)] [.next-rail-wait-controls_&]:px-2.5 [.next-rail-wait-controls_&]:py-[5px]';
/* A refused control rests calm: a muted fill, the control border kept solid so it still reads as a button,
   and muted ink. No hatch and no dashed edge, which the owner rejected on 2026-11-24
   ([calm disabled look](../../../docs/design-calm-compass.md#buttons-and-the-calm-disabled-look-2026-11-24)). */
const refused =
  'disabled:border-solid disabled:border-[var(--line)] disabled:bg-muted disabled:text-[color:var(--ink3)] disabled:cursor-not-allowed aria-disabled:not-aria-busy:border-solid aria-disabled:not-aria-busy:border-[var(--line)] aria-disabled:not-aria-busy:bg-muted aria-disabled:not-aria-busy:text-[color:var(--ink3)] aria-disabled:not-aria-busy:cursor-not-allowed aria-busy:border-solid aria-busy:bg-none aria-busy:text-foreground aria-busy:cursor-progress';
const solidLabel = 'text-primary-foreground aria-busy:text-primary-foreground';
const solid = `border-[var(--accent)] bg-primary hover:border-[var(--accent)] ${solidLabel}`;
const dangerEdge = 'border-destructive hover:border-destructive';
/* The canvas `.btn`: 600-weight label, 18 px either side and 8 px between a glyph and its words, on the
   12 px control radius every button and field shares. */
const button = cn(action, 'gap-2 px-[18px] font-semibold');
const emphasized = cn(button, refused);
const raiseState =
  'data-[raise-state=sent]:border-[var(--accent)] data-[raise-state=declined]:border-[var(--line)] data-[raise-state=failed]:border-[var(--line)] data-[raise-state=throttled]:border-[var(--amber)] data-[raise-state=stale]:border-[var(--amber)] data-[raise-state=refused]:border-[var(--amber)] data-[raise-state]:not-data-[raise-state=sent]:not-data-[raise-state=sending]:text-muted-foreground data-[raise-state]:not-data-[raise-state=sent]:not-data-[raise-state=sending]:bg-muted aria-disabled:not-aria-busy:bg-none aria-disabled:not-aria-busy:bg-transparent data-[raise-state=sending]:cursor-progress';
const buttonVariants = cva(
  'min-h-[44px] min-w-[44px] max-w-full box-border [overflow-wrap:anywhere] focus-visible:outline-2 focus-visible:outline-solid focus-visible:outline-ring focus-visible:outline-offset-2 [&[hidden]]:hidden',
  {
    variants: {
      variant: {
        default: cn(button, refused),
        retry: cn(
          button,
          refused,
          'aria-disabled:not-aria-busy:border-solid aria-disabled:not-aria-busy:cursor-wait disabled:border-solid disabled:cursor-wait',
        ),
        answer: cn(action, refused, 'px-[11px] py-[7px] hover:border-[var(--accent)]'),
        primary: cn(button, refused, solid),
        quiet: cn(button, refused),
        bare: cn(
          action,
          'bg-[var(--sunk)] [display:flow-root] [line-height:normal] justify-normal items-normal',
        ),
        window: cn(
          action,
          'bg-[var(--sunk)] block [line-height:normal] justify-normal items-normal hover:border-[var(--line)]',
        ),
        menu: cn(
          action,
          'flex justify-between border-0 border-none border-current bg-transparent p-2',
        ),
        'context-add': cn(
          action,
          'block justify-normal items-normal border-0 border-none border-current bg-transparent text-muted-foreground',
        ),
        native: '',
        segment: cn(
          action,
          refused,
          /* The canvas's segmented control: plain words on the track, the chosen one a white bordered tab.
             A refused segment takes the calm refused look with its border drawn. */
          'rounded-card border-transparent px-4 py-1 font-medium text-[var(--status-quiet-ink)] hover:border-transparent hover:not-disabled:bg-accent disabled:border-[var(--line)] aria-pressed:border-[var(--line)] aria-pressed:bg-card aria-pressed:font-semibold aria-pressed:text-foreground aria-pressed:shadow-[0_1px_2px_rgb(31_41_51/12%)]',
        ),
        'filter-option': cn(
          action,
          refused,
          'rounded-pill gap-2 px-3 py-1 bg-card hover:bg-accent aria-pressed:border-[var(--accent)] aria-pressed:bg-accent aria-pressed:font-semibold',
        ),
        /* A removable filter: one press removes it, so the remove glyph sits inside the button's name. */
        'filter-chip': cn(
          action,
          'inline-flex gap-1.5 px-2.5 py-1 rounded-pill border-[var(--line)] bg-[var(--sunk)] text-body leading-[1.4] text-start hover:border-[var(--accent)]',
        ),
        copy: cn(
          button,
          refused,
          'text-muted-foreground hover:border-[var(--accent)] hover:text-foreground data-[copy-state=copied]:border-[var(--accent)] data-[copy-state=copied]:text-foreground data-[copy-state=failed]:border-[var(--amber)] data-[copy-state=failed]:text-muted-foreground',
        ),
        raise: cn(
          action,
          refused,
          'px-[7px] py-1 border-[var(--amber)] bg-[var(--sunk)] font-[family-name:var(--mono)] font-bold hover:border-[var(--ink)]',
          raiseState,
        ),
        'raise-primary': cn(
          action,
          refused,
          solid,
          'font-[family-name:var(--mono)] font-bold',
          raiseState,
        ),
        terminal: cn(
          action,
          'px-2.5 py-[7px] text-muted-foreground text-label leading-normal hover:bg-[var(--panel)] hover:text-foreground',
        ),
      },
      emphasis: {
        primary: cn(
          emphasized,
          solid,
          'hover:not-disabled:not-aria-disabled:bg-[var(--accent-dim)]',
        ),
        secondary: cn(emphasized, 'bg-card hover:bg-accent'),
        quiet: cn(
          emphasized,
          'border-transparent text-primary hover:border-transparent hover:bg-accent',
        ),
        danger: cn(
          emphasized,
          dangerEdge,
          'bg-card text-destructive hover:bg-danger-outline-hover',
        ),
        'danger-solid': cn(
          emphasized,
          dangerEdge,
          solidLabel,
          'bg-[var(--destructive-solid)] hover:not-disabled:not-aria-disabled:bg-danger-hover',
        ),
      },
      tone: {
        default: '',
        muted: 'text-muted-foreground',
      },
      size: {
        default: '',
        consent: 'px-3.5 py-[6px]',
      },
      accentBorder: { true: 'border-[var(--accent)]', false: '' },
      strongBorder: { true: 'border-2', false: '' },
    },
    defaultVariants: { variant: 'default' },
  },
);

export interface ButtonProps extends ComponentProps<'button'>, VariantProps<typeof buttonVariants> {
  readonly busyLabel?: ReactNode;
  readonly reserve?: ReactNode;
}

function Spinner({ idle = false }: { readonly idle?: boolean }) {
  return (
    <svg
      data-slot="spinner"
      aria-hidden="true"
      viewBox="0 0 16 16"
      className={cn(
        'size-[1em] shrink-0 motion-reduce:opacity-[.55]',
        !idle && 'animate-[spin_.8s_linear_infinite] motion-reduce:animate-none',
      )}
    >
      <circle
        cx="8"
        cy="8"
        r="6"
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
        strokeDasharray="28 10"
      />
    </svg>
  );
}

function Button({
  className,
  variant,
  emphasis,
  tone,
  size,
  accentBorder,
  strongBorder,
  busyLabel,
  reserve,
  children,
  disabled,
  onClick,
  onKeyDown,
  onKeyUp,
  ...props
}: ButtonProps) {
  const busy = props['aria-busy'] === true || props['aria-busy'] === 'true';
  return (
    <ButtonPrimitive
      {...props}
      data-slot="button"
      data-variant={variant ?? 'default'}
      data-emphasis={emphasis ?? undefined}
      disabled={!busy && disabled}
      aria-disabled={busy ? true : props['aria-disabled']}
      // Base UI's focusable disabled path cancels shell navigation keys as well as activation.
      onKeyDown={(event) => {
        if (busy && (event.key === 'Enter' || event.key === ' ')) event.preventDefault();
        onKeyDown?.(event);
      }}
      onKeyUp={(event) => {
        if (busy && (event.key === 'Enter' || event.key === ' ')) event.preventDefault();
        onKeyUp?.(event);
      }}
      onClick={(event) => {
        if (busy) event.preventDefault();
        else onClick?.(event);
      }}
      className={cn(
        buttonVariants({ variant, emphasis, tone, size, accentBorder, strongBorder }),
        (busy && busyLabel !== undefined) || reserve
          ? 'relative inline-grid items-center justify-items-center [&>span]:[grid-area:1/1]'
          : '',
        className,
      )}
    >
      {busy && busyLabel !== undefined ? (
        <>
          <span
            data-slot="button-ghost"
            aria-hidden="true"
            className={cn('invisible', reserve && 'inline-grid [&>span]:[grid-area:1/1]')}
          >
            {reserve ? (
              <>
                <span>{children}</span>
                <span className="inline-flex items-center gap-1.5">
                  <Spinner idle />
                  {reserve}
                </span>
              </>
            ) : (
              children
            )}
          </span>
          <span
            data-slot="button-busy"
            className="absolute inset-0 inline-flex items-center justify-center gap-1.5"
          >
            <Spinner />
            {busyLabel}
          </span>
        </>
      ) : reserve ? (
        <span data-slot="button-reserve" className="contents [&>span]:[grid-area:1/1]">
          <span>{children}</span>
          <span data-slot="button-ghost" aria-hidden="true" className="invisible flex">
            <span className="inline-flex items-center gap-1.5">
              <Spinner idle />
              {reserve}
            </span>
          </span>
        </span>
      ) : (
        children
      )}
    </ButtonPrimitive>
  );
}

export { Button, buttonVariants };
