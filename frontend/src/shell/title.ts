import type { PayloadData } from '../api/types';
import { SHOWN } from '../language/glossary';
import type { Route } from '../router/grammar';
import { SAMPLE_FIXTURE } from '../sample/fixture';
import { isSampleRoute } from '../sample/ids';
import { findSession, sessionTitle } from './derive';

/* One title per view, stable while the board refreshes: it changes only when the route does, or when
   the session it names publishes a different title. A session the board cannot find takes its own id,
   never a made-up name. */
export function documentTitle(route: Route, data: PayloadData | null): string {
  switch (route.view) {
    case 'project':
      return `${route.project} — ${SHOWN.compass}`;
    case 'session': {
      const board = isSampleRoute(route) ? (SAMPLE_FIXTURE.board as unknown as PayloadData) : data;
      const session = findSession(board, route.project, route.harness, route.session);
      const title = session ? sessionTitle(session) : String(route.session || SHOWN.session);
      return `${title} — ${route.project} — ${SHOWN.compass}`;
    }
    default:
      return `${SHOWN.compass} — ${SHOWN[route.view]}`;
  }
}
