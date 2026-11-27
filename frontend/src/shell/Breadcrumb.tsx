import { RouteLink } from './RouteLink';
import { Icon } from '../ui/icons';
import { SHOWN } from '../language/glossary';
import { sessionHome, type Route } from '../router/grammar';
import { planShown } from '../api/plan';
import type { PayloadData } from '../api/types';
import { SAMPLE_FIXTURE } from '../sample/fixture';
import { isSampleRoute } from '../sample/ids';
import { findSession, sessionTitle } from './derive';
import { useDisplayed } from './context';
import { pageTitleOf } from '../observed/session';
import type { Row } from '../observed';

/* The crumb a reader sees for the location they are in. Top-level views carry none. A session's crumb
   starts at the view the reader came from (a pasted link carries no origin and starts at Sessions), and
   Escape walks back to its last link. The session's own label is its published title, or the sentence
   that says there is none; before the session can be found it is the word "Session", which claims
   nothing about a board nobody has read. */
export function Breadcrumb({ route }: { readonly route: Route }) {
  const data = useDisplayed((snapshot) => snapshot.data);
  const plan = useDisplayed((snapshot) => planShown(snapshot.plan));
  if (route.view !== 'project' && route.view !== 'session') return null;
  const projects = (
    <RouteLink className="next-crumb" route={{ view: 'projects' }}>
      {SHOWN.projects}
    </RouteLink>
  );
  const separator = (
    <Icon name="caret-right" className="next-breadcrumb-current-separator shrink-0" />
  );
  let trail;
  if (route.view === 'project') {
    trail = (
      <>
        {projects}
        {separator}
        <span aria-current="page" data-authored>
          {route.project}
        </span>
      </>
    );
  } else {
    /* The sample's session is on its own board, not the one this page polls, so its crumb reads its title there. */
    const board = isSampleRoute(route) ? (SAMPLE_FIXTURE.board as unknown as PayloadData) : data;
    const session = findSession(board, route.project, route.harness, route.session);
    const label = session ? sessionTitle(session) : SHOWN.session;
    const current = (
      <>
        {separator}
        <span
          aria-current="page"
          data-authored={Boolean(session && pageTitleOf(session as unknown as Row)) || undefined}
        >
          {label}
        </span>
      </>
    );
    const home = sessionHome(route, { plan });
    if (home !== 'projects') {
      trail = (
        <>
          <RouteLink className="next-crumb" route={{ view: home }}>
            {SHOWN[home]}
          </RouteLink>
          {current}
        </>
      );
    } else if (!route.project) {
      trail = (
        <>
          {projects}
          {current}
        </>
      );
    } else {
      trail = (
        <>
          {projects}
          <Icon name="caret-right" />
          <RouteLink className="next-crumb" route={{ view: 'project', project: route.project }}>
            <span data-authored>{route.project}</span>
          </RouteLink>
          {current}
        </>
      );
    }
  }
  return (
    <nav className="next-breadcrumb" aria-label={SHOWN.breadcrumb}>
      {trail}
    </nav>
  );
}
