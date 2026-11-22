import { nextNumber } from '../api/bootstrap';
import type { BoardRisk } from './capacity';
import { sessionState, type ObservedSession } from './session';
import { goalOf } from './landing';
import { locationNote } from './location';
import { compare, pair, sessionKey, type Pair, type Row } from './values';

/* A project here is a group of sessions that publish one label, exactly as published. The legacy model
   also hangs two project panels off this object (the workstream's state changes and the delegation
   windows); those are computed from the project step's own stores and belong to that step, so the
   object carries room for them as `history` and this step leaves it `null`. */
export type ObservedProject = {
  readonly key: string;
  readonly countLine: string;
  readonly goalSrcText: string;
  readonly goalSrcKnown: boolean;
  readonly goalAt: number | null;
  readonly goalGapText: string;
  readonly goalGapKnown: boolean;
  readonly sessions: readonly ObservedSession[];
  readonly needs: readonly ObservedSession[];
  readonly working: readonly ObservedSession[];
  readonly ended: readonly ObservedSession[];
  readonly risky: readonly ObservedSession[];
  readonly sharedLabelText: string;
  readonly sharedLabelKnown: boolean;
  readonly tone: 'ok' | 'want' | 'bad' | 'unknown';
  /** The project step's windows, which this step does not compute. */
  readonly history: null;
} & Pair<'scope'> &
  Pair<'goal'>;

export function observeProject(
  key: string,
  sessions: readonly ObservedSession[],
  sources: readonly Row[],
  risky: readonly ObservedSession[],
): ObservedProject {
  const needs = sessions.filter((session) => session.isNeeds || session.askKnown);
  const nativeNeeds = sessions.filter((session) => session.isNeeds).length;
  const working = sessions.filter((session) => session.isWorking);
  const ended = sessions.filter((session) => session.isEnded);
  const quiet = sessions.filter((session) => sessionState(session) === 'Quiet');
  const counts = [`${String(sessions.length)} ${sessions.length === 1 ? 'session' : 'sessions'}`];
  if (working.length) counts.push(`${String(working.length)} working`);
  if (nativeNeeds) counts.push(`${String(nativeNeeds)} waiting on you`);
  if (ended.length) counts.push(`${String(ended.length)} ended`);
  if (quiet.length) counts.push(`${String(quiet.length)} quiet`);
  const other = sessions.length - working.length - nativeNeeds - ended.length - quiet.length;
  if (other) counts.push(`${String(other)} in no counted state`);
  const goals = sources.flatMap((source) => {
    const goal = goalOf(source);
    return goal ? [{ source, goal }] : [];
  });
  /* The most recently active session's goal stands for the project; a tie falls to the session key, so
     the choice is the same on every render. */
  goals.sort(
    (a, b) =>
      (nextNumber(b.source['last_activity']) ?? 0) - (nextNumber(a.source['last_activity']) ?? 0) ||
      compare(sessionKey(a.source), sessionKey(b.source)),
  );
  const goal = goals[0]?.goal ?? false;
  return {
    key,
    ...pair('scope', '', 'Exact location not published'),
    countLine: counts.join(' · '),
    // The project speaks for the whole label, so it takes the label's note, not one row's.
    ...pair('sharedLabel', locationNote(sources), 'No shared display label observed'),
    ...pair('goal', goal && goal.text, 'No assignment or workflow goal published'),
    goalSrcText: goal ? goal.src : 'Goal source not published',
    goalSrcKnown: Boolean(goal),
    // The raw stamp, not a formatted age: a duration derived here would be as old as the last derivation,
    // and the render is what knows the clock.
    goalAt: goal && goal.at !== null ? goal.at : null,
    goalGapText: `${String(sessions.length - goals.length)} of ${String(sessions.length)} ${sessions.length === 1 ? 'session publishes' : 'sessions publish'} no goal.`,
    goalGapKnown: true,
    sessions,
    needs,
    working,
    ended,
    risky,
    history: null,
    tone:
      needs.length || sessions.some((session) => session.askKnown)
        ? 'want'
        : risky.some((session) => session.tone === 'bad')
          ? 'bad'
          : risky.length
            ? 'want'
            : sessions.some((session) => session.tone === 'ok')
              ? 'ok'
              : 'unknown',
  } as ObservedProject;
}

/* A risk carried by one session: its identity is the label and the sid as published, and its "now" is
   the sentence that put it here. The risk never owns the session's identity beyond those strings. */
export function sessionRisk(
  session: ObservedSession,
  kind: string,
  title: string,
  text: string,
): BoardRisk {
  return {
    scope: 'session',
    kind,
    sid: session.sid,
    harness: session.harness,
    project: session.project,
    title,
    identity: `${session.project} · ${session.sid}`,
    src: session.harness,
    nowText: text,
    nowKnown: true,
    nextText: session.nextText,
    nextKnown: session.nextKnown,
    tone: session.tone,
  };
}
