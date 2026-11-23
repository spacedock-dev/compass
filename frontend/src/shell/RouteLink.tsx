import { buttonVariants } from '../ui/button';
import { cn } from '../lib/utils';
import type { MouseEvent, ReactNode, Ref } from 'react';
import { fragmentForRoute, type RouteInput } from '../router/grammar';
import { useNavigate } from './context';

export interface RouteLinkProps {
  readonly route: RouteInput;
  readonly ref?: Ref<HTMLAnchorElement> | undefined;
  readonly current?: boolean;
  readonly className?: string;
  readonly variant?: NonNullable<Parameters<typeof buttonVariants>[0]>['variant'];
  readonly children: ReactNode;
}

/* A link to a route that every producer of a route should use: it prints the canonical fragment as its
   `href`, so it opens in a new tab and copies as a link, and a plain click goes through the router, which
   stamps where a session was opened from. A modified click or a non-primary button is the browser's own. */
export function RouteLink({
  route,
  className,
  variant = 'native',
  children,
  ref,
  current,
}: RouteLinkProps) {
  const navigate = useNavigate();
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
    navigate(route);
  };
  return (
    <a
      ref={ref}
      aria-current={current ? 'page' : undefined}
      data-slot="button-link"
      href={fragmentForRoute(route)}
      className={cn(buttonVariants({ variant }), className)}
      onClick={onClick}
    >
      {children}
    </a>
  );
}
