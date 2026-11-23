import { nextNumber } from '../api/bootstrap';
import { GLOSSARY } from '../language/glossary';
import { observedFor } from '../observed/select';
import { endedAt, sessionStateLimit, type Row } from '../observed';
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
