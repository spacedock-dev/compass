import { SampleInvite } from '../sample/SampleInvite';
import { buttonVariants } from '../ui/button';
import { payloadSessions } from '../api/bootstrap';
import { compatSessKey } from '../api/identity';
import {
  fragmentForRoute,
  type ProjectRoute,
  type Route,
  type SessionRoute,
  type TopLevelRoute,
} from '../router/grammar';
import type { BoardSnapshot } from '../store/board';
import { selectDataStatus } from '../store/selectors';
import { findSession, windowHours } from './derive';
import { RouteLink } from './RouteLink';
import { useDisplayed } from './context';
import { AttentionView } from '../attention';
import { IntentLog } from '../intent';
import { useLiveMonitorLease } from '../intent/liveMonitor';
import { SampleSession } from '../sample/SampleSession';
import { isSampleRoute } from '../sample/ids';
import { SessionDetail, SessionsView } from '../sessions';
import { SettingsView } from '../settings';
import { PROJECT_SLOTS, ProjectDetail, ProjectsView } from '../project';
import type { Row } from '../observed';

const HEADINGS: Readonly<Record<'sessions' | 'projects', string>> = {
  sessions: 'Session operations',
  projects: 'Projects',
};

/* Unread is not unavailable, and neither is an empty board: a view says which of the three it is. */
function BoardStatus({ snapshot }: { readonly snapshot: BoardSnapshot }) {
  const status = selectDataStatus(snapshot);
  if (status === 'unread')
    return <p className="next-absence">The first payload has not arrived yet.</p>;
  if (status === 'unavailable')
    return <p className="next-absence">No data has been received in this tab.</p>;
  return null;
}

/* Sessions is the landing view. Before the first payload and after reads that never succeeded it says so,
   and a board that carried no session collection says that, because "no sessions" would be a claim about a
   collection nobody published. */
function SessionsBranch() {
  const snapshot = useDisplayed((current) => current);
  if (!snapshot.data) {
    return (
      <section className="next-view" data-next-view-body="sessions">
        <h1>{HEADINGS.sessions}</h1>
        <BoardStatus snapshot={snapshot} />
      </section>
    );
  }
  if (!payloadSessions(snapshot.data).present) {
    return (
      <section
        className="next-view"
        data-next-view-body="sessions"
        data-next-sessions-state="no-collection"
      >
        <h1>{HEADINGS.sessions}</h1>
        <p className="next-absence">The board published no session collection.</p>
      </section>
    );
  }
  return <SessionsView />;
}

/* Projects is the Sessions collection grouped by label, so it states the same two absences before it draws:
   no board yet, and a board that carried no session collection, which "no projects" would misreport. */
function ProjectsBranch() {
  const snapshot = useDisplayed((current) => current);
  if (!snapshot.data) {
    return (
      <section className="next-projects" data-next-view-body="projects">
        <h1>{HEADINGS.projects}</h1>
        <BoardStatus snapshot={snapshot} />
      </section>
    );
  }
  if (!payloadSessions(snapshot.data).present) {
    return (
      <section
        className="next-projects"
        data-next-view-body="projects"
        data-next-projects-state="no-collection"
      >
        <h1>{HEADINGS.projects}</h1>
        <p className="next-absence">The board published no session collection.</p>
      </section>
    );
  }
  return <ProjectsView conditions={PROJECT_SLOTS.projectsConditions?.() ?? null} />;
}

function TopLevelView({ route }: { readonly route: TopLevelRoute }) {
  if (route.view === 'sessions')
    return (
      <>
        <SampleInvite />
        <SessionsBranch />
      </>
    );
  if (route.view === 'projects') return <ProjectsBranch />;
  /* The Intent log states its own absences (annotations off, store unreadable, still reading), so it
     draws before the first payload as well: it names what it is waiting for rather than a blank. */
  if (route.view === 'intent') return <IntentLog />;
  /* Settings reads its own route, not the board, so it draws whether or not a payload has arrived. */
  if (route.view === 'settings') return <SettingsView />;
  /* Attention states its own absences as well: before the first board it names what it waits for, and a
     board that published no session collection says that rather than drawing a queue of zeros. */
  return <AttentionView />;
}

function SessionView({ route }: { readonly route: SessionRoute }) {
  const data = useDisplayed((snapshot) => snapshot.data);
  /* A pasted link lands here before the first payload does, and "not in the payload" would then be a
     claim about a payload nobody has read. */
  if (!data) {
    return (
      <section
        className="next-session-detail-empty"
        data-next-view-body="session"
        data-next-session-state="unread"
      >
        <p className="next-absence">The first payload has not arrived yet.</p>
      </section>
    );
  }
  const session = findSession(data, route.project, route.harness, route.session);
  if (!session) {
    /* Named, because a pasted link is the usual way here and the reader needs to know which session
       the board no longer holds. The window is stated as a fact about the board, never as the cause:
       a session from another machine is absent for a different reason. */
    const who = [route.harness, route.session].filter(Boolean).join(' · ');
    const hours = windowHours(data);
    return (
      <section
        className="next-session-detail-empty"
        data-next-view-body="session"
        data-next-session-state="outside-payload"
      >
        <p className="next-absence">This session is not in the current payload.</p>
        {who ? <p className="next-session-identity">{who}</p> : null}
        {hours !== null && hours > 0 ? (
          <p>{`The board holds sessions observed in the last ${String(hours)} ${hours === 1 ? 'hour' : 'hours'}.`}</p>
        ) : null}
        <RouteLink route={{ view: 'sessions', project: null, session: null }}>
          View all sessions
        </RouteLink>
      </section>
    );
  }
  return (
    <>
      <LiveMonitorLease session={session as unknown as Row} payload={data as unknown as Row} />
      <SessionDetail route={route} data={data} session={session as unknown as Row} />
    </>
  );
}

/* The Live monitor's lease for the session on screen: nothing is drawn, and the lease lives exactly as long as
   this is mounted, so leaving the route, or moving to another session, ends it. */
function LiveMonitorLease({ session, payload }: { readonly session: Row; readonly payload: Row }) {
  useLiveMonitorLease(session, payload);
  return null;
}

function ProjectView({ route }: { readonly route: ProjectRoute }) {
  const data = useDisplayed((snapshot) => snapshot.data);
  const collection = payloadSessions(data);
  if (!data) {
    return (
      <section
        className="next-project-detail-empty"
        data-next-view-body="project"
        data-next-project-state="unread"
      >
        <p className="next-absence">The first payload has not arrived yet.</p>
      </section>
    );
  }
  if (!collection.present) {
    return (
      <section
        className="next-project-detail-empty"
        data-next-view-body="project"
        data-next-project-state="no-collection"
      >
        <p className="next-absence">The board published no session collection.</p>
      </section>
    );
  }
  const members = collection.rows.filter((row) => String(row.project ?? '') === route.project);
  if (members.length === 0) {
    return (
      <section
        className="next-project-detail-empty"
        data-next-view-body="project"
        data-next-project-state="outside-payload"
      >
        <p className="next-absence">Not present in the current payload.</p>
        <RouteLink route={{ view: 'projects', project: null, session: null }}>
          View all projects
        </RouteLink>
      </section>
    );
  }
  /* A focus is the exact compatibility key of one session of this project. One the board no longer holds
     is stated, with the way back to the project root, rather than silently showing the whole project. */
  if (route.focus && !members.some((row) => compatSessKey(row) === route.focus)) {
    return (
      <section
        className="next-cockpit-stale-session"
        data-next-view-body="project"
        data-next-cockpit-stale-session
      >
        <span>SESSION FILTER</span>
        <h1>Session filter is outside this payload window</h1>
        <p>{route.focus}</p>
        <a
          data-slot="button-link"
          className={buttonVariants({ variant: 'native' })}
          href={fragmentForRoute({
            view: 'project',
            project: route.project,
            tab: route.tab ?? 'now',
          })}
        >
          View project root
        </a>
      </section>
    );
  }
  return <ProjectDetail route={route} slots={PROJECT_SLOTS} />;
}

export function RoutedView({ route }: { readonly route: Route }) {
  switch (route.view) {
    case 'session':
      /* The sample reads its own shell, so it never depends on, or touches, the board this page is polling. */
      return isSampleRoute(route) ? (
        <SampleSession>
          <SessionView route={route} />
        </SampleSession>
      ) : (
        <SessionView route={route} />
      );
    case 'project':
      return <ProjectView route={route} />;
    default:
      return <TopLevelView route={route} />;
  }
}
