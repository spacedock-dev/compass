import { exactIdentity } from '../api/identity';
import { attentionSelectionFor } from '../attention/select';
import { SESSION_ROW_WORDS, SHOWN } from '../language/glossary';
import {
  payloadSessionRows,
  sessionKey,
  sessionState,
  type ObservedSession,
  type Row,
} from '../observed';
import { observedFor } from '../observed/select';
import { compare } from '../observed/values';

export const PROJECT_STATES = ['Waiting on you', 'Working', 'Ended', 'Quiet'] as const;

export interface ProjectSession {
  readonly key: string;
  readonly session: ObservedSession;
  readonly source: Row | undefined;
  readonly identity: ReturnType<typeof exactIdentity>;
  readonly state: ReturnType<typeof sessionState>;
  readonly reason: string | undefined;
}

export function projectSessionGroups(payload: Row): ReadonlyMap<string, readonly ProjectSession[]> {
  const observed = observedFor(payload);
  const sources = payloadSessionRows(payload);
  const occurrence = new Map(observed.sessions.map((session, index) => [session, index]));
  const selection = attentionSelectionFor(payload);
  const flags = new Map<ObservedSession | string, string>();
  for (const [session, reason] of selection?.worthALook ?? []) {
    flags.set(
      exactIdentity(session) ? JSON.stringify([session.project, sessionKey(session)]) : session,
      reason,
    );
  }
  const groups = new Map<string, Map<string, ProjectSession>>();
  // Keep the board's ordering and prefer a waiting occurrence when one identity was published twice.
  for (const session of [...observed.active, ...observed.history]) {
    const index = occurrence.get(session);
    const identity = exactIdentity(session);
    const key = identity ? sessionKey(session) : `occurrence:${String(index)}`;
    const project = groups.get(session.project) ?? new Map<string, ProjectSession>();
    groups.set(session.project, project);
    const waiting = session.isNeeds || session.askKnown;
    const previous = project.get(key);
    if (previous && (!waiting || previous.state === 'Waiting on you')) continue;
    project.set(key, {
      key,
      session,
      identity,
      source: index === undefined ? undefined : sources[index],
      state: waiting ? 'Waiting on you' : sessionState(session),
      reason: waiting
        ? undefined
        : flags.get(identity ? JSON.stringify([session.project, key]) : session),
    });
  }
  return new Map([...groups].map(([project, rows]) => [project, [...rows.values()]]));
}

export function projectStateCounts(rows: readonly ProjectSession[]) {
  const counts = new Map<ProjectSession['state'], number>();
  let flagged = 0;
  for (const row of rows) {
    counts.set(row.state, (counts.get(row.state) ?? 0) + 1);
    if (row.reason) flagged += 1;
  }
  return [
    ...PROJECT_STATES.map((word) => ({ word, count: counts.get(word) ?? 0 })),
    { word: SESSION_ROW_WORDS.worthALook, count: flagged },
  ];
}

export function projectInstruction(rows: readonly ProjectSession[]) {
  const working = rows.filter((row) => row.state === 'Working');
  const current = working.map(({ session }) => session).filter((session) => session.ownGoalKnown);
  const candidates = current.length
    ? current
    : rows.map(({ session }) => session).filter((session) => session.ownGoalKnown);
  candidates.sort(
    (a, b) =>
      (b.ownGoalAt ?? -1) - (a.ownGoalAt ?? -1) ||
      (b.lastActivityAt ?? 0) - (a.lastActivityAt ?? 0) ||
      compare(sessionKey(a), sessionKey(b)),
  );
  const session = candidates[0];
  return session
    ? {
        text: session.ownGoalText,
        at: session.ownGoalAt,
        current: current.length > 0,
        dated: candidates.every((row) => row.ownGoalAt !== null),
      }
    : null;
}

export function projectSessionLabels(
  rows: readonly ProjectSession[],
  harnesses: ReadonlyMap<string, string>,
) {
  const labels = new Map(
    rows.map(({ session, key }) => [
      key,
      {
        title: session.titleKnown ? session.titleText : SHOWN.titleNotPublished,
        harness: harnesses.get(session.harness) || session.harness || 'Agent not published',
        detail: '',
      },
    ]),
  );
  const faces = new Map<string, string[]>();
  for (const [key, { title, harness }] of labels) {
    const face = JSON.stringify([title, harness]);
    const keys = faces.get(face) ?? [];
    keys.push(key);
    faces.set(face, keys);
  }
  for (const keys of faces.values()) {
    if (keys.length < 2) continue;
    keys.sort(compare).forEach((key, index) => {
      const label = labels.get(key);
      if (label) label.detail = `${SHOWN.session} ${String(index + 1)}`;
    });
  }
  return labels;
}
