import { buttonVariants } from '../ui/button';
import { Icon } from '../ui/icons';
import { AttentionAnnouncer } from '../attention';
import { selectAttentionSelection } from '../attention/select';
import { NotificationControl } from '../notify';
import { useFocusKey } from '../controls/useFocusKey';
import { cn } from '../lib/utils';
import { SHOWN } from '../language/glossary';
import { sessionHome, type Route, type TopLevelView } from '../router/grammar';
import { RouteLink } from './RouteLink';
import { useDisplayed, useShell } from './context';

const PRIMARY = ['sessions', 'projects', 'attention', 'intent', 'settings', 'help'] as const;

/* The view a route sits under: a session sits under the view it was opened from, a project under Projects. */
function currentView(route: Route): TopLevelView {
  if (route.view === 'session') return sessionHome(route);
  return route.view === 'project' ? 'projects' : route.view;
}

function PrimaryNavigation({
  route,
  needsCount,
}: {
  readonly route: Route;
  readonly needsCount: number;
}) {
  const { controls } = useShell();
  const here = currentView(route);
  /* The current item is the focus lane's fallback for a control that stands only while something is
     wrong (Retry now), so removing it hands focus to a place the reader can see. */
  const currentRef = useFocusKey<HTMLAnchorElement>(controls.focusLane, 'primary-current');
  return (
    <nav aria-label={SHOWN.primary} className="flex flex-wrap items-center gap-x-1">
      {PRIMARY.map((view) => (
        <RouteLink
          className="gap-2 rounded-card px-3 text-body font-medium text-foreground no-underline hover:bg-muted aria-[current=page]:bg-[var(--status-ended-bg)] aria-[current=page]:font-semibold aria-[current=page]:text-[var(--status-ended-ink)] forced-colors:aria-[current=page]:underline"
          key={view}
          ref={view === here ? currentRef : undefined}
          route={{ view }}
          current={view === here}
        >
          {SHOWN[view]}
          {view === 'attention' && needsCount > 0 ? (
            <>
              {' '}
              <span className="inline-grid min-w-5 place-items-center rounded-pill bg-[var(--amber)] px-1 text-label leading-5 font-semibold text-primary-foreground">
                {needsCount}
              </span>
            </>
          ) : null}
        </RouteLink>
      ))}
    </nav>
  );
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
  return (
    <header className="-mt-[18px] -mx-[26px] flex min-h-16 flex-wrap items-center justify-between gap-x-5 gap-y-2 border-b border-[var(--rule)] bg-card px-4 py-2 [@media(max-width:760px)]:mx-0">
      <div className="flex flex-wrap items-center gap-x-5">
        <a
          data-slot="button-link"
          className={cn(
            buttonVariants({ variant: 'native' }),
            'gap-2.5 rounded-control text-value font-bold text-foreground no-underline',
          )}
          href="#n=sessions"
        >
          <Icon name="compass" size="1.35em" className="text-primary" />
          {SHOWN.compass}
        </a>
        <PrimaryNavigation route={route} needsCount={counts?.badge ?? 0} />
      </div>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
        <NotificationControl />
        <WorkingPill count={counts?.working} unread={unread} />
      </div>
      <AttentionAnnouncer />
    </header>
  );
}
