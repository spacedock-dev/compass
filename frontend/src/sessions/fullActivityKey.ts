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

/* Entry jumps write both reader-state lanes before asking the Activity log to focus a row. */
export function showActivityLog(
  controls: Controls,
  project: string,
  session: Row,
  keepCited = false,
): void {
  const key = fullActivityKey(project, session);
  controls.technicalTabs.remember(key, ACTIVITY_LOG);
  if (!keepCited || controls.activityLogFilters.read(key) !== 'cited')
    controls.activityLogFilters.forget(key);
  controls.disclosures.set(key, true);
}
