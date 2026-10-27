import { buttonVariants } from '../ui/button';
import { cn } from '../lib/utils';
import { fragmentForRoute, sessionHome, type Route, type TopLevelView } from '../router/grammar';
import type { PayloadData } from '../api/types';
import { SAMPLE_FIXTURE } from '../sample/fixture';
import { isSampleRoute } from '../sample/ids';
import { findSession, sessionTitle } from './derive';
import { useDisplayed } from './context';

const HOME_LABEL: Readonly<Record<Exclude<TopLevelView, 'projects'>, string>> = {
  sessions: 'Sessions',
  attention: 'Attention',
  intent: 'Intent log',
};

/* The crumb a reader sees for the location they are in. Top-level views carry none. A session's crumb
   starts at the view the reader came from (a pasted link carries no origin and starts at Sessions), and
   Escape walks back to its last link. The session's own label is its published title, or the sentence
   that says there is none; before the session can be found it is the word "Session", which claims
   nothing about a board nobody has read. */
export function Breadcrumb({ route }: { readonly route: Route }) {
  const data = useDisplayed((snapshot) => snapshot.data);
  if (route.view !== 'project' && route.view !== 'session') return null;
  const projects = (
    <a
      data-slot="button-link"
      className={cn('next-crumb', buttonVariants({ variant: 'native' }))}
      href="#n=projects"
    >
      Projects
    </a>
  );
  const separator = (
    <span className="next-breadcrumb-current-separator" aria-hidden="true">
      {' › '}
    </span>
  );
  let trail;
  if (route.view === 'project') {
    trail = (
      <>
        {projects}
        {separator}
        <span aria-current="page">{route.project}</span>
      </>
    );
  } else {
    /* The sample's session is on its own board, not the one this page polls, so its crumb reads its title there. */
    const board = isSampleRoute(route) ? (SAMPLE_FIXTURE.board as unknown as PayloadData) : data;
    const session = findSession(board, route.project, route.harness, route.session);
    const label = session ? sessionTitle(session) : 'Session';
    const current = (
      <>
        {separator}
        <span aria-current="page">{label}</span>
      </>
    );
    const home = sessionHome(route);
    if (home !== 'projects') {
      trail = (
        <>
          <a
            data-slot="button-link"
            className={cn('next-crumb', buttonVariants({ variant: 'native' }))}
            href={`#n=${home}`}
          >
            {HOME_LABEL[home]}
          </a>
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
          <span aria-hidden="true">{' › '}</span>
          <a
            data-slot="button-link"
            className={cn('next-crumb', buttonVariants({ variant: 'native' }))}
            href={fragmentForRoute({ view: 'project', project: route.project })}
          >
            {route.project}
          </a>
          {current}
        </>
      );
    }
  }
  return (
    <nav className="next-breadcrumb" aria-label="Breadcrumb">
      {trail}
    </nav>
  );
}
