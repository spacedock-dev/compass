import { compatSessKey } from '../api/identity';
import { disclosureKey } from '../controls/disclosureStore';
import type { Row } from '../observed';

/* The open state of a session's Full activity, keyed like every other session disclosure so a refresh, a
   remount or a citation that opens it all write the one entry (docs/design-reader-state.md#the-inventory). */
export function fullActivityKey(project: string, session: Row): string {
  return disclosureKey({ project, scope: compatSessKey(session), name: 'full-activity' });
}
