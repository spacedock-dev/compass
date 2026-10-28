import { buttonVariants } from '../ui/button';
import { Icon } from '../ui/icons';
import { Button } from '../ui/button';
import { AttentionAnnouncer } from '../attention';
import { MoreMenu } from '../controls/MoreMenu';
import { NotificationControl } from '../notify';
import { useFocusKey } from '../controls/useFocusKey';
import { splitSessKey, stableProjectKey } from '../api/identity';
import { payloadSessions } from '../api/bootstrap';
import { sessionHome, type Route } from '../router/grammar';
import { useDisplayed, useNavigate, useShell } from './context';
import { selectHeaderCounts, type HeaderCounts } from './derive';
import { useProjectBriefing } from './projectBriefing';

/* Every member of the top-level set gets an entry, and Attention is not optional: it was once absent
   here while the router, the title and the `a` shortcut all knew it, which left a whole screen reachable
   only by typing a fragment. Sessions comes first so the first step is opening a session. */
const PRIMARY = [
  ['sessions', 'Sessions'],
  ['projects', 'Projects'],
  ['attention', 'Attention'],
  ['intent', 'Intent log'],
  ['settings', 'Settings'],
] as const;

/* The view a route sits under: a session sits under the view it was opened from, a project under Projects. */
function currentView(route: Route): string {
  if (route.view === 'session') return sessionHome(route);
  return route.view === 'project' ? 'projects' : route.view;
}

function PrimaryNavigation({ route }: { readonly route: Route }) {
  const { controls } = useShell();
  const here = currentView(route);
  /* The current item is the focus lane's fallback for a control that stands only while something is
     wrong (Retry now), so removing it hands focus to a place the reader can see. */
  const currentRef = useFocusKey<HTMLAnchorElement>(controls.focusLane, 'primary-current');
  return (
    <nav aria-label="Primary">
      {PRIMARY.map(([view, label]) =>
        view === here ? (
          <a
            data-slot="button-link"
            className={buttonVariants({ variant: 'native' })}
            key={view}
            ref={currentRef}
            href={`#n=${view}`}
            aria-current="page"
          >
            {label}
          </a>
        ) : (
          <a
            data-slot="button-link"
            className={buttonVariants({ variant: 'native' })}
            key={view}
            href={`#n=${view}`}
          >
            {label}
          </a>
        ),
      )}
    </nav>
  );
}

/* Counts are read from the same rows the views render, never authored. Before a board has arrived, and
   when the board carried no session collection, nothing is known, so nothing is claimed: no zero, and no
   "live" dot, which would say the board is being watched when there is no board. */
function RunningCounts({ counts }: { readonly counts: HeaderCounts }) {
  if (counts.state === 'unread')
    return <span className="next-running">Waiting for the first board.</span>;
  if (counts.state === 'absent')
    return <span className="next-running">Session data not published.</span>;
  return (
    <span className="next-running next-live">
      <span className="next-status-dot" aria-label="live">
        ●
      </span>
      {` ${String(counts.running)} running · ${String(counts.subagents)} ${counts.subagents === 1 ? 'subagent' : 'subagents'} observed`}
    </span>
  );
}

function ProjectMore({
  route,
  counts,
}: {
  readonly route: Extract<Route, { view: 'project' }>;
  readonly counts: HeaderCounts;
}) {
  const data = useDisplayed((snapshot) => snapshot.data);
  const briefing = useProjectBriefing(route);
  if (counts.state !== 'measured') return null;
  const rows = payloadSessions(data).rows.filter(
    (row) => String(row.project ?? '') === route.project,
  );
  const projectKey = stableProjectKey({ label: route.project, sessions: rows });
  return (
    <MoreMenu
      projectKey={projectKey}
      focus={route.focus ? splitSessKey(route.focus) : null}
      running={counts.running}
      subagents={counts.subagents}
      briefingText={briefing.briefingText}
      {...(briefing.addHumanContext ? { addHumanContext: briefing.addHumanContext } : {})}
    />
  );
}

export function Header({ route }: { readonly route: Route }) {
  const navigate = useNavigate();
  const counts = useDisplayed(selectHeaderCounts);
  const detail = route.view === 'project';
  return (
    <header className="next-header">
      <div className="next-header-left flex flex-wrap items-center gap-x-7">
        <span className="inline-flex items-center gap-2 text-value font-bold text-foreground">
          <Icon name="compass" size="1.15em" className="text-primary" />
          Compass
        </span>
        <PrimaryNavigation route={route} />
      </div>
      <div className="next-header-right">
        {detail ? null : <RunningCounts counts={counts} />}
        {counts.state === 'measured' && counts.gates > 0 ? (
          <Button
            variant="native"
            type="button"
            className="next-gate"
            data-next-action="needs-input"
            onClick={() => navigate({ view: 'attention', project: null, session: null })}
          >
            {`${String(counts.gates)} ${counts.gates === 1 ? 'reported block' : 'reported blocks'}`}
          </Button>
        ) : null}
        <NotificationControl />
        {route.view === 'project' ? <ProjectMore route={route} counts={counts} /> : null}
        <AttentionAnnouncer />
      </div>
    </header>
  );
}
