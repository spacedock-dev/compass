import { buttonVariants } from '../ui/button';
import { cn } from '../lib/utils';
import type { ReactNode, Ref } from 'react';
import { sessionState } from '../observed';
import { Icon, SESSION_STATE_ICONS } from '../ui/icons';
import type { ObservedSession } from '../observed';
import { fragmentForRoute, type RouteInput } from '../router/grammar';
import { useNavigate } from '../shell/context';

/* The small parts every project view is drawn from. */

/* A fact that knows whether it was measured: the sentence for what is known, and for what is not, the
   reason it is not, in the absence ink, so an unmeasured value never reads as a quieter measured one. */
export function Value({
  text,
  known,
  className = '',
}: {
  readonly text: string;
  readonly known: boolean;
  readonly className?: string;
}) {
  return (
    <span
      className={`next-project-value ${known ? 'next-project-value--known' : 'next-project-value--absent'}${className ? ` ${className}` : ''}`}
    >
      {text}
    </span>
  );
}

export function ProjectSessionStatus({ session }: { readonly session: ObservedSession }) {
  const state = sessionState(session);
  if (state === 'State not published') return null;
  return (
    <span
      className={cn('inline-flex', session.isLive && state === 'Working' && 'next-live')}
      role="img"
      aria-label={state}
    >
      <Icon name={SESSION_STATE_ICONS[state]} className="next-status-icon shrink-0" />
    </span>
  );
}

export function Absence({ children }: { readonly children: ReactNode }) {
  return <p className="next-absence">{children}</p>;
}

/* An anchor to a route that keeps the released fragment as its `href`, so it opens in a new tab and copies
   as a link, and sends a plain click through the router. A modified click or a non-primary button is the
   browser's own. It carries the page's `data-next-route` token and takes a ref, which the focus lane needs
   to put focus back on the very link a reader chose. */
export function ProjectAnchor({
  route,
  linkRef,
  className,
  extra,
  children,
}: {
  readonly route: RouteInput;
  readonly linkRef?: Ref<HTMLAnchorElement>;
  readonly className?: string;
  readonly extra?: Record<string, string>;
  readonly children: ReactNode;
}) {
  const navigate = useNavigate();
  const fragment = fragmentForRoute(route);
  return (
    <a
      data-slot="button-link"
      ref={linkRef}
      href={fragment}
      data-next-route={fragment.slice(3)}
      className={cn(className, buttonVariants({ variant: 'native' }))}
      {...extra}
      onClick={(event) => {
        if (
          event.defaultPrevented ||
          event.button !== 0 ||
          event.metaKey ||
          event.ctrlKey ||
          event.shiftKey ||
          event.altKey
        )
          return;
        event.preventDefault();
        navigate(route);
      }}
    >
      {children}
    </a>
  );
}
