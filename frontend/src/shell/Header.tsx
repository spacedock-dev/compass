import { buttonVariants } from '../ui/button';
import { Icon } from '../ui/icons';
import { Button } from '../ui/button';
import { AttentionAnnouncer } from '../attention';
import { MoreMenu } from '../controls/MoreMenu';
import { NotificationControl } from '../notify';
import { useFocusKey } from '../controls/useFocusKey';
import { splitSessKey, stableProjectKey } from '../api/identity';
import { payloadSessions } from '../api/bootstrap';
import { SHOWN } from '../language/glossary';
import { sessionHome, type Route, type TopLevelView } from '../router/grammar';
import { useDisplayed, useNavigate, useShell } from './context';
import { selectHeaderCounts, type HeaderCounts } from './derive';
import { useProjectBriefing } from './projectBriefing';

/* Every member of the top-level set gets an entry, and Attention is not optional: it was once absent
   here while the router, the title and the `a` shortcut all knew it, which left a whole screen reachable
   only by typing a fragment. Sessions comes first so the first step is opening a session. */
const PRIMARY = ['sessions', 'projects', 'attention', 'intent', 'settings'] as const;

const countLabel = (template: string, count: number): string =>
  template.replace('{count}', String(count));

/* The view a route sits under: a session sits under the view it was opened from, a project under Projects. */
function currentView(route: Route): TopLevelView {
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
    <nav aria-label={SHOWN.primary}>
      {PRIMARY.map((view) => (
        <a
          data-slot="button-link"
          className={buttonVariants({ variant: 'native' })}
          key={view}
          ref={view === here ? currentRef : undefined}
          href={`#n=${view}`}
          aria-current={view === here ? 'page' : undefined}
        >
          {SHOWN[view]}
        </a>
      ))}
    </nav>
  );
}

/* Counts are read from the same rows the views render, never authored. Before a board has arrived, and
   when the board carried no session collection, nothing is known, so nothing is claimed: no zero, and no
   "live" dot, which would say the board is being watched when there is no board. */
function RunningCounts({ counts }: { readonly counts: HeaderCounts }) {
  if (counts.state === 'unread')
    return <span className="next-running">{SHOWN.waitingForBoard}</span>;
  if (counts.state === 'absent')
    return <span className="next-running">{SHOWN.sessionDataNotPublished}</span>;
  const running = countLabel(SHOWN.runningCount, counts.running);
  const subagents = countLabel(
    counts.subagents === 1 ? SHOWN.subagentCountOne : SHOWN.subagentCountMany,
    counts.subagents,
  );
  return (
    <span className="next-running next-live">
      {counts.running ? (
        <Icon name="working" className="next-status-icon inline-block shrink-0" />
      ) : null}
      {` ${running} · ${subagents}`}
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
          {SHOWN.compass}
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
            {countLabel(
              counts.gates === 1 ? SHOWN.reportedBlockCountOne : SHOWN.reportedBlockCountMany,
              counts.gates,
            )}
          </Button>
        ) : null}
        <NotificationControl />
        {route.view === 'project' ? <ProjectMore route={route} counts={counts} /> : null}
        <AttentionAnnouncer />
      </div>
    </header>
  );
}
