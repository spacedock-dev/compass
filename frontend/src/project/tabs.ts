import type { ProjectTab } from '../router/grammar';
import type { ContextRead } from '../store/selectors';
import { clock } from '../observed/values';
import { decisionFacts } from './recovery';
import { field, isRecord } from './raw';

/* What each project tab says about itself: one sentence naming its own word and what its panel holds, and
   a cue on the tab for what the panel would count. The cue is honest about five states of the board: a
   figure, a collection read and found empty, one nobody has published, one whose context has not arrived,
   and one that was read and did not come back. Ported from `next-cockpit.js`. */

const LEDES: Readonly<Record<ProjectTab, string>> = {
  now: 'Sessions and recent results for this project.',
  course: 'Direction changes Compass observed in the session record.',
  decisions: 'Decisions Compass found in the session record.',
  console: 'Usage and alerts for this project.',
};

/* Now is the one tab whose scope does not narrow with the selection, so a reader who has just picked a
   session is the only one who needs telling. */
export function tabLede(tab: ProjectTab, focused: boolean): string {
  const lede = LEDES[tab];
  const scope =
    tab === 'now' && focused
      ? ' It stays project-wide, including activity from other sessions.'
      : '';
  return `${lede}${scope}`;
}

const NOUNS: Readonly<Record<string, readonly [string, string]>> = {
  course: ['observed state change', 'observed state changes'],
  decisions: ['decision', 'decisions'],
};

export type CueState = 'count' | 'zero' | 'pending' | 'unobserved' | 'unavailable';

export interface TabCue {
  readonly state: CueState;
  readonly value: number;
  /** The read behind the figure has failed to refresh since: the count is real, its age is in doubt. */
  readonly stale: boolean;
  readonly lastRead: number | null;
}

const count = (length: number): Pick<TabCue, 'state' | 'value'> =>
  length > 0 ? { state: 'count', value: length } : { state: 'zero', value: 0 };

export interface CueInput {
  /** The Course tab's own collection: the state changes this tab observed, as a count. */
  readonly changes: number;
  readonly read: ContextRead;
}

/* Only Course and Decisions count anything. Neither a read in flight nor one that failed is "nothing
   published", and calling it that would report the schema rather than the session. */
export function tabCue(tab: ProjectTab, input: CueInput): TabCue | null {
  const base = ((): Pick<TabCue, 'state' | 'value'> | null => {
    if (tab === 'course') return count(input.changes);
    if (tab === 'decisions') {
      const { read } = input;
      if (!read.shows)
        return { state: read.state === 'unavailable' ? 'unavailable' : 'pending', value: 0 };
      const semantic = field(read.entry?.data ?? null, 'semantic');
      if (!isRecord(semantic) || !Array.isArray(semantic['facts']))
        return { state: 'unobserved', value: 0 };
      return count(decisionFacts(semantic).length);
    }
    return null;
  })();
  if (!base) return null;
  const stale = input.read.state === 'stale';
  return {
    ...base,
    stale,
    lastRead: stale ? (input.read.entry?.revision ?? null) : null,
  };
}

/** The visible mark, which is aria-hidden: the gloss carries the same claim for a screen reader. */
export function cueMark(cue: TabCue): string {
  return cue.state === 'pending'
    ? '…'
    : cue.state === 'unobserved'
      ? '·'
      : cue.state === 'unavailable'
        ? '—'
        : String(cue.value);
}

/* The two channels must agree. A visible suffix with no change to the gloss would tell a sighted reader
   the rows are stale and a screen-reader user they are current. */
export function cueGloss(tab: ProjectTab, cue: TabCue): string {
  const nouns = NOUNS[tab] ?? ['item', 'items'];
  const gloss =
    cue.state === 'count'
      ? `${String(cue.value)} ${cue.value === 1 ? nouns[0] : nouns[1]}`
      : cue.state === 'zero'
        ? `No ${nouns[1]} observed`
        : cue.state === 'pending'
          ? `${nouns[1]} not loaded yet`
          : cue.state === 'unavailable'
            ? `${nouns[1]} could not be read`
            : `${nouns[1]} not published`;
  if (!cue.stale) return gloss;
  const at = cue.lastRead ? clock(cue.lastRead) : '';
  return `${gloss}${at ? `, last read ${at}, refresh has failed since` : ', refresh has failed since the last successful read'}`;
}
