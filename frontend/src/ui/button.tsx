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
const refused =
  'disabled:border-dashed disabled:bg-[image:var(--hatch)] disabled:text-[color:var(--ink3)] disabled:cursor-not-allowed aria-disabled:not-aria-busy:border-dashed aria-disabled:not-aria-busy:bg-[image:var(--hatch)] aria-disabled:not-aria-busy:text-[color:var(--ink3)] aria-disabled:not-aria-busy:cursor-not-allowed aria-busy:border-solid aria-busy:bg-none aria-busy:text-foreground aria-busy:cursor-progress';
const raiseState =
  'data-[raise-state=sent]:border-[var(--accent)] data-[raise-state=declined]:border-[var(--line)] data-[raise-state=failed]:border-[var(--line)] data-[raise-state=throttled]:border-[var(--amber)] data-[raise-state=stale]:border-[var(--amber)] data-[raise-state=declined]:text-muted-foreground data-[raise-state=failed]:text-muted-foreground data-[raise-state=throttled]:text-muted-foreground data-[raise-state=stale]:text-muted-foreground aria-disabled:not-aria-busy:bg-none aria-disabled:not-aria-busy:bg-transparent data-[raise-state=sending]:cursor-progress';
const buttonVariants = cva(
  'min-h-[44px] min-w-[44px] max-w-full box-border [overflow-wrap:anywhere] focus-visible:outline-2 focus-visible:outline-solid focus-visible:outline-[var(--accent)] focus-visible:outline-offset-1 [&[hidden]]:hidden',
  {
    variants: {
      variant: {
        default: cn(action, refused),
        retry: cn(
          action,
          refused,
          'aria-disabled:not-aria-busy:border-solid aria-disabled:not-aria-busy:cursor-wait disabled:border-solid disabled:cursor-wait',
        ),
        answer: cn(action, refused, 'px-[11px] py-[7px] hover:border-[var(--accent)]'),
        primary: cn(
          action,
          refused,
          'aria-busy:border-[var(--accent)] aria-busy:bg-primary aria-busy:text-[color:var(--bg)]',
        ),
        quiet: cn(action, refused),
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
        /* A removable filter: one press removes it, so the remove glyph sits inside the button's name. */
        'filter-chip': cn(
          action,
          'inline-flex gap-1.5 px-2.5 py-1 rounded-pill border-[var(--line)] bg-[var(--sunk)] text-body leading-[1.4] text-start hover:border-[var(--accent)]',
        ),
        copy: cn(
          action,
          refused,
          'text-muted-foreground hover:border-[var(--accent)] hover:text-foreground data-[copy-state=copied]:border-[var(--accent)] data-[copy-state=copied]:text-foreground data-[copy-state=failed]:border-[var(--amber)] data-[copy-state=failed]:text-muted-foreground focus-visible:outline-offset-2',
        ),
        raise: cn(
          action,
          refused,
          'px-[7px] py-1 border-[var(--amber)] bg-[var(--sunk)] font-[family-name:var(--mono)] font-bold hover:border-[var(--ink)] focus-visible:outline-offset-2',
          raiseState,
        ),
        'raise-primary': cn(
          action,
          refused,
          'border-[var(--accent)] bg-primary text-[color:var(--bg)] font-[family-name:var(--mono)] font-bold focus-visible:outline-[var(--ink)] focus-visible:outline-offset-2',
          raiseState,
        ),
        terminal: cn(
          action,
          'px-2.5 py-[7px] text-muted-foreground text-label leading-normal hover:bg-[var(--panel)] hover:text-foreground focus-visible:outline-offset-3',
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
  variant = 'default',
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
        buttonVariants({ variant, tone, size, accentBorder, strongBorder }),
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
