import type { Controls } from '../controls/kit';
import { compatSessKey } from '../api/identity';
import { disclosureKey } from '../controls/disclosureStore';
import type { Row } from '../observed';

/* The open state of a session's Activity log, keyed like every other session disclosure so a refresh, a
   remount or a citation that opens it all write the one entry (docs/design-reader-state.md#the-inventory). */
export const ACTIVITY_LOG = 'activity-log';

export function fullActivityKey(project: string, session: Row): string {
  return disclosureKey({ project, scope: compatSessKey(session), name: 'full-activity' });
}

/* Entry jumps select and open the Activity log before asking it to focus a row. */
export function showActivityLog(controls: Controls, project: string, session: Row): void {
  const key = fullActivityKey(project, session);
  controls.technicalTabs.remember(key, ACTIVITY_LOG);
  controls.disclosures.set(key, true);
}
