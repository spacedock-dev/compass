import { nextNumber } from '../api/bootstrap';
import { attentionSelectionFor } from '../attention/select';
import { GLOSSARY, SESSION_ROW_WORDS } from '../language/glossary';
import { observedFor } from '../observed/select';
import { endedAt, payloadSessionRows, sessionStateLimit, type Row } from '../observed';
import { formatTimestamp, observationAge } from '../shell/format';
import { goalScope } from './goal';
import { compare } from '../observed/values';

export const PROJECT_GROUPS = ['Active today', 'No recent activity'] as const;
export const UNNAMED_FOLDER = 'Unnamed folder';
const words = SESSION_ROW_WORDS;
const STATES = [words.waitingOnYou, words.working, words.ended, words.quiet] as const;

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
  const selection = attentionSelectionFor(payload);
  const now = nextNumber(payload['generated']);
  const ends = new Map<string, number>();
  for (const source of payloadSessionRows(payload)) {
    const key = String(source['project'] ?? '');
    const end = endedAt(source);
    if (end !== null && observationAge(now, end) !== null)
      ends.set(key, Math.max(end, ends.get(key) ?? 0));
  }
  const byState = [
    selection?.waitingOnYou ?? [],
    selection?.working ?? [],
    selection?.ended ?? [],
    selection?.quiet ?? [],
    [...(selection?.worthALook.keys() ?? [])],
  ];
  const byProject = byState.map((rows) => {
    const counts = new Map<string, number>();
    for (const { project } of rows) counts.set(project, (counts.get(project) ?? 0) + 1);
    return counts;
  });
  const rows = projects.map((project) => {
    const counts = [...STATES, words.worthALook].map((word, index) => ({
      word,
      count: byProject[index]?.get(project.key) ?? 0,
    }));
    const rank = counts.slice(0, STATES.length).findIndex(({ count }) => count > 0);
    const state = STATES[rank] ?? GLOSSARY.stateNotPublished.plain;
    const end = ends.get(project.key) ?? null;
    const wait = project.needs.find((session) => session.askKnown || session.blockKnown);
    const instruction = goalScope(project, null);
    const latest = project.sessions.reduce(
      (at, session) =>
        observationAge(now, session.lastActivityAt) !== null
          ? Math.max(at, session.lastActivityAt ?? 0)
          : at,
      end ?? 0,
    );
    const waitingHint = wait?.askKnown ? wait.askText : wait?.blockKnown ? wait.blockText : '';
    const headline = wait?.askKnown
      ? waitingHint
      : instruction.known
        ? instruction.text
        : waitingHint;
    const limit =
      rank < 0
        ? project.sessions.map((session) => sessionStateLimit(session)).find(Boolean) ||
          'State not published'
        : '';
    return {
      key: project.key,
      name: project.key || UNNAMED_FOLDER,
      state,
      rank: rank < 0 ? STATES.length : rank,
      headline,
      limit,
      group:
        rank === 0 || rank === 1 || endedToday(end, now) ? PROJECT_GROUPS[0] : PROJECT_GROUPS[1],
      counts: counts.filter(({ count }) => count > 0),
      sessions: project.sessions.length,
      latest,
      time: formatTimestamp(latest, now, { style: 'same-day-relative' }),
    };
  });
  return rows.sort((a, b) => a.rank - b.rank || b.latest - a.latest || compare(a.key, b.key));
}

export type ProjectListRow = ReturnType<typeof projectList>[number];
