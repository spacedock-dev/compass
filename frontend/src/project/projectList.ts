import { nextNumber } from '../api/bootstrap';
import { GLOSSARY } from '../language/glossary';
import { observedFor } from '../observed/select';
import { endedAt, sessionStateLimit, type ObservedSession, type Row } from '../observed';
import { formatTimestamp, observationAge } from '../shell/format';
import {
  PROJECT_STATES,
  projectInstruction,
  projectSessionGroups,
  projectStateCounts,
} from './projectActivity';
import { compare } from '../observed/values';

export const PROJECT_GROUPS = ['Active today', 'No recent activity'] as const;
export const UNNAMED_FOLDER = 'Unnamed folder';

export function endedToday(ended: number | null, generated: number | null): boolean {
  return (
    ended !== null &&
    generated !== null &&
    observationAge(generated, ended) !== null &&
    new Date(ended * 1000).toDateString() === new Date(generated * 1000).toDateString()
  );
}

export interface ProjectCompanions {
  /** Other sessions in the project that are active today: working, waiting on you, or ended today. */
  readonly today: number;
  /** Of those, the ones working. */
  readonly working: number;
}

/* The Session page's Project card line, counted from the same rows Projects groups. A session counts as today
   by the Active today rule above: Waiting on you or Working, or a reported end on the board's calendar day. The
   session the page is about is left out by its exact harness and id. */
export function projectCompanions(
  payload: Row,
  session: Pick<ObservedSession, 'project' | 'harness' | 'sid'>,
): ProjectCompanions {
  const now = nextNumber(payload['generated']);
  const others = (projectSessionGroups(payload).get(session.project) ?? []).filter(
    (member) => !(member.session.harness === session.harness && member.session.sid === session.sid),
  );
  const today = others.filter(
    ({ state, source }) =>
      state === 'Waiting on you' || state === 'Working' || endedToday(endedAt(source), now),
  );
  return { today: today.length, working: today.filter(({ state }) => state === 'Working').length };
}

/* "2 other sessions today · 1 working". Nothing when no other session was active today, and no working clause
   when none is working: a zero would be a count of nothing on a line that exists to point somewhere. */
export function companionsLine(companions: ProjectCompanions | null): string {
  if (!companions || companions.today < 1) return '';
  const head = `${String(companions.today)} other session${companions.today === 1 ? '' : 's'} today`;
  return companions.working > 0 ? `${head} · ${String(companions.working)} working` : head;
}

export function projectList(payload: Row) {
  const { projects } = observedFor(payload);
  const groups = projectSessionGroups(payload);
  const now = nextNumber(payload['generated']);
  const rows = projects.map((project) => {
    const members = groups.get(project.key) ?? [];
    const counts = projectStateCounts(members);
    const rank = PROJECT_STATES.findIndex((_, index) => (counts[index]?.count ?? 0) > 0);
    const state = PROJECT_STATES[rank] ?? GLOSSARY.stateNotPublished.plain;
    const wait = members.find(({ state }) => state === 'Waiting on you')?.session;
    const instruction = projectInstruction(members);
    const dates = members.flatMap(({ session, source }) => [
      session.lastActivityAt,
      endedAt(source),
    ]);
    const latest = dates.reduce<number>(
      (at, stamp) => (observationAge(now, stamp) === null ? at : Math.max(at, stamp ?? 0)),
      0,
    );
    const waitingHint = wait?.askKnown ? wait.askText : wait?.blockKnown ? wait.blockText : '';
    const headline = wait?.askKnown ? waitingHint : instruction?.text || waitingHint;
    const limits = [
      ...new Set(members.map(({ session }) => sessionStateLimit(session)).filter(Boolean)),
    ];
    const ended = members.some(({ source }) => endedToday(endedAt(source), now));
    return {
      key: project.key,
      name: project.key || UNNAMED_FOLDER,
      state,
      rank: rank < 0 ? PROJECT_STATES.length : rank,
      headline,
      headlineIsEarlier: headline === instruction?.text && !instruction.current,
      limits,
      location: project.sharedLabelKnown ? project.sharedLabelText : '',
      group: rank === 0 || rank === 1 || ended ? PROJECT_GROUPS[0] : PROJECT_GROUPS[1],
      counts: counts.filter(({ count }) => count > 0),
      sessions: members.length,
      latest,
      time: formatTimestamp(latest, now, { style: 'same-day-relative' }),
    };
  });
  return rows.sort((a, b) => a.rank - b.rank || b.latest - a.latest || compare(a.key, b.key));
}

export type ProjectListRow = ReturnType<typeof projectList>[number];
