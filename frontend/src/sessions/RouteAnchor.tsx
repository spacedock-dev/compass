import { buttonVariants } from '../ui/button';
import { cn } from '../lib/utils';
import { useContext, type MouseEvent, type ReactNode } from 'react';
import { ControlsContext } from '../controls/kit';
import { useFocusKey } from '../controls/useFocusKey';
import { fragmentForRoute, type RouteInput } from '../router/grammar';
import { useNavigate } from '../shell/context';

/* A link to a route that keeps the released fragment as its `href` (so it opens in a new tab and copies as
   a link) and sends a plain click through the router, which stamps where a session was opened from. A
   modified click or a non-primary button is the browser's own. A `focusKey` registers the link with the focus
   lane, so a focused link that a redraw removes hands focus to its replacement or to `fallback`. */
export function RouteAnchor({
  route,
  className,
  label,
  extra,
  before,
  focusKey,
  fallback,
  children,
}: {
  readonly route: RouteInput;
  readonly className?: string;
  readonly label?: string;
  readonly extra?: Record<string, string>;
  readonly before?: () => void;
  readonly focusKey?: string;
  readonly fallback?: string;
  readonly children: ReactNode;
}) {
  const navigate = useNavigate();
  // Read without `useControls`, which throws, so a link drawn outside the controls still renders.
  const lane = useContext(ControlsContext)?.focusLane ?? null;
  const ref = useFocusKey<HTMLAnchorElement>(
    lane,
    focusKey ?? null,
    fallback === undefined ? {} : { fallback },
  );
  const fragment = fragmentForRoute(route);
  const onClick = (event: MouseEvent<HTMLAnchorElement>) => {
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
    before?.();
    navigate(route);
  };
  return (
    <a
      ref={ref}
      data-slot="button-link"
      className={cn(className, buttonVariants({ variant: 'native' }))}
      href={fragment}
      data-next-route={fragment.slice(3)}
      {...(label ? { 'aria-label': label } : {})}
      {...extra}
      onClick={onClick}
    >
      {children}
    </a>
  );
}
