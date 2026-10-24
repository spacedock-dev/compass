import { PreviewCard } from '@base-ui/react/preview-card';
import { useContext, useRef, useState, type ComponentProps, type ReactNode } from 'react';
import { DriftContext } from './context';
import { evidenceRows } from './level';
import { citedLine } from './result';

/* A citation: its number as a link. Hovering or focusing it shows the cited entry's own words in place, so
   reading a summary never means leaving it; "See in context of the session" is the press that closes the card,
   opens Full activity and lands on the entry. Pressing the number itself opens the card and does not jump, so
   a citation is never a surprise scroll. A keyboard press puts focus on the context link, because the card
   is drawn outside the line it belongs to. The card is a convenience only: the context link is the same press
   the number used to be, and an entry the page does not hold yet says so and keeps that press, which reads the
   older pages for it. */
const LINK =
  'min-h-0 min-w-0 rounded-control font-[family-name:var(--mono)] text-label text-cite no-underline hover:underline focus-visible:outline-2 focus-visible:outline-solid focus-visible:outline-[var(--accent)] focus-visible:outline-offset-1';

export function CitationLink({
  id,
  onJump,
  className = '',
  children,
  ...props
}: {
  readonly id: string;
  /** The jump to the entry in Full activity; `origin` is the number the reader pressed, where focus returns. */
  readonly onJump: (origin: HTMLElement | null) => void;
  readonly className?: string;
  readonly children: ReactNode;
} & Omit<ComponentProps<'a'>, 'onClick' | 'href' | 'children'>) {
  const drift = useContext(DriftContext);
  const [open, setOpen] = useState(false);
  const trigger = useRef<HTMLAnchorElement | null>(null);
  const context = useRef<HTMLAnchorElement | null>(null);
  const entry = drift?.model.byId.get(id) ?? null;
  const row = entry
    ? evidenceRows([id], drift?.model.numbers ?? new Map(), drift?.model.byId ?? new Map())[0]
    : undefined;
  return (
    <PreviewCard.Root open={open} onOpenChange={setOpen}>
      <PreviewCard.Trigger
        ref={trigger}
        href="#"
        delay={250}
        closeDelay={150}
        className={`${LINK} ${className}`}
        onClick={(event) => {
          event.preventDefault();
          setOpen(true);
          if (event.detail === 0)
            requestAnimationFrame(() => requestAnimationFrame(() => context.current?.focus()));
        }}
        {...props}
      >
        {children}
      </PreviewCard.Trigger>
      <PreviewCard.Portal>
        <PreviewCard.Positioner
          side="top"
          align="start"
          sideOffset={6}
          collisionPadding={16}
          className="isolate z-[4] max-w-[calc(100vw-32px)]"
        >
          <PreviewCard.Popup
            data-next-citation-card={id}
            className="box-border flex w-[min(24rem,calc(100vw-32px))] flex-col gap-2 rounded-control border border-solid border-[var(--line)] bg-[var(--raise)] px-3 py-2.5 text-body text-foreground shadow-[0_18px_44px_-22px_#000] outline-none transition-opacity duration-[var(--disclose-pop-dur)] ease-[var(--disclose-ease)] data-[starting-style]:opacity-0 data-[ending-style]:opacity-0 motion-reduce:transition-none"
          >
            {entry && row ? (
              <>
                <p className="m-0 text-label text-muted-foreground [font-family:var(--mono)]">
                  {row.shown.head}
                </p>
                <p
                  className="m-0 line-clamp-6 text-body leading-[1.5] [overflow-wrap:anywhere]"
                  data-next-citation-snippet
                >
                  {citedLine(entry)}
                </p>
              </>
            ) : (
              <p className="m-0 text-body leading-[1.5] text-muted-foreground">
                This entry is from earlier in the session and is not loaded yet. Seeing it in
                context reads the older record pages for it.
              </p>
            )}
            <a
              ref={context}
              href="#"
              className={`${LINK} w-fit text-body`}
              data-next-citation-context
              onClick={(event) => {
                event.preventDefault();
                setOpen(false);
                onJump(trigger.current);
              }}
            >
              See in context of the session
            </a>
          </PreviewCard.Popup>
        </PreviewCard.Positioner>
      </PreviewCard.Portal>
    </PreviewCard.Root>
  );
}
