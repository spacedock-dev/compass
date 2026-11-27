import { useEffect, useId, useRef, useState } from 'react';
import { Button, buttonVariants } from '../ui/button';
import { Icon } from '../ui/icons';
import { planShown } from '../api/plan';
import { AttentionAnnouncer } from '../attention';
import { selectAttentionSelection } from '../attention/select';
import { useFocusKey } from '../controls/useFocusKey';
import { cn } from '../lib/utils';
import { SHOWN } from '../language/glossary';
import { sessionHome, type Route, type TopLevelView } from '../router/grammar';
import { RouteLink } from './RouteLink';
import { useDisplayed, useShell } from './context';

const PRIMARY = [
  'sessions',
  'projects',
  'attention',
  'intent',
  'plan',
  'settings',
  'help',
] as const;

/* The view a route sits under: a session sits under the view it was opened from, a project under Projects. */
function currentView(route: Route): TopLevelView {
  if (route.view === 'session') return sessionHome(route);
  return route.view === 'project' ? 'projects' : route.view;
}

function PrimaryNavigation({
  route,
  needsCount,
  panelId,
  open,
}: {
  readonly route: Route;
  readonly needsCount: number;
  readonly panelId: string;
  readonly open: boolean;
}) {
  const { controls } = useShell();
  const here = currentView(route);
  const hasPlan = useDisplayed((snapshot) => planShown(snapshot.plan));
  /* The current item is the focus lane's fallback for a control that stands only while something is
     wrong (Retry now), so removing it hands focus to a place the reader can see. */
  const currentRef = useFocusKey<HTMLAnchorElement>(controls.focusLane, 'primary-current');
  return (
    <nav
      id={panelId}
      aria-label={SHOWN.primary}
      data-compact-open={open || undefined}
      className="next-board-nav flex-wrap items-center gap-x-1"
    >
      {PRIMARY.filter((view) => view !== 'plan' || hasPlan).map((view) => (
        <RouteLink
          className="gap-2 rounded-card px-3 text-body font-medium text-foreground no-underline hover:bg-muted aria-[current=page]:bg-[var(--status-ended-bg)] aria-[current=page]:font-semibold aria-[current=page]:text-[var(--status-ended-ink)] forced-colors:aria-[current=page]:underline"
          key={view}
          ref={view === here ? currentRef : undefined}
          route={{ view }}
          current={view === here}
        >
          {SHOWN[view]}
          {view === 'attention' ? <NeedsBadge count={needsCount} /> : null}
        </RouteLink>
      ))}
    </nav>
  );
}

function NeedsBadge({ count }: { readonly count: number }) {
  return count > 0 ? (
    <>
      {' '}
      <span className="inline-grid min-w-5 place-items-center rounded-pill bg-[var(--amber)] px-1 text-label leading-5 font-semibold text-primary-foreground">
        {count}
      </span>
    </>
  ) : null;
}

function WorkingPill({
  count,
  unread,
}: {
  readonly count: number | undefined;
  readonly unread: boolean;
}) {
  const label =
    count === undefined
      ? unread
        ? SHOWN.waitingForBoard
        : SHOWN.sessionDataNotPublished
      : count === 0
        ? SHOWN.nothingWorking
        : (count === 1 ? SHOWN.workingCountOne : SHOWN.workingCountMany).replace(
            '{count}',
            String(count),
          );
  const working = (count ?? 0) > 0;
  return (
    <span
      role="status"
      aria-label={SHOWN.workingSessions}
      className={cn(
        'inline-flex items-center gap-1.5 rounded-pill px-2.5 py-0.5 text-label font-semibold',
        working
          ? 'bg-[var(--status-working-bg)] text-[var(--status-working-ink)]'
          : 'bg-muted text-muted-foreground',
      )}
    >
      {working ? (
        <span aria-hidden="true" className="size-2 shrink-0 rounded-pill bg-current" />
      ) : null}
      {label}
    </span>
  );
}

export function Header({ route }: { readonly route: Route }) {
  const selection = useDisplayed(selectAttentionSelection);
  const counts = selection?.counts;
  const unread = useDisplayed((snapshot) => snapshot.data === null);
  const { router } = useShell();
  const menu = useRef<HTMLButtonElement>(null);
  const panelId = useId();
  const [open, setOpen] = useState(false);
  useEffect(() => {
    if (!open) return;
    const close = () => {
      setOpen(false);
      menu.current?.focus({ preventScroll: true });
    };
    const onEscape = (event: KeyboardEvent) => {
      if (
        event.key !== 'Escape' ||
        event.defaultPrevented ||
        !menu.current?.getClientRects().length
      )
        return;
      event.preventDefault();
      close();
    };
    const unsubscribe = router.subscribe(close);
    document.addEventListener('keydown', onEscape);
    return () => {
      unsubscribe();
      document.removeEventListener('keydown', onEscape);
    };
  }, [open, router]);

  return (
    <header className="next-board-header -mt-[18px] -mx-[26px] min-h-16 flex-wrap items-center gap-y-2 border-b border-[var(--rule)] bg-card py-2 [@media(max-width:760px)]:mx-0">
      <a
        data-slot="button-link"
        aria-label={SHOWN.compass}
        className={cn(
          buttonVariants({ variant: 'native' }),
          'next-board-brand inline-flex items-center justify-center gap-2 rounded-control text-value font-bold text-foreground no-underline',
        )}
        href="#n=sessions"
      >
        <Icon name="compass" size="1.35em" className="text-primary" />
        <span className="next-board-brand-label">{SHOWN.compass}</span>
      </a>
      <div className="next-board-compact">
        <Button
          type="button"
          aria-current={currentView(route) === 'attention' ? 'page' : undefined}
          className="gap-1 px-2 text-label font-semibold"
          onClick={() => router.navigate({ view: 'attention' })}
        >
          {SHOWN.attention}
          <NeedsBadge count={counts?.badge ?? 0} />
        </Button>
        <Button
          ref={menu}
          type="button"
          aria-label="Menu"
          className="gap-1 px-2"
          aria-expanded={open}
          aria-controls={panelId}
          onClick={() => setOpen(!open)}
        >
          <Icon name="menu" size={20} />
        </Button>
      </div>
      <PrimaryNavigation
        route={route}
        needsCount={counts?.badge ?? 0}
        panelId={panelId}
        open={open}
      />
      <div className="next-board-working">
        <WorkingPill count={counts?.working} unread={unread} />
      </div>
      <AttentionAnnouncer />
    </header>
  );
}
