import { nextNumber } from '../api/bootstrap';
import {
  clock,
  endedAt,
  isScanOnly,
  pair,
  promptCopied,
  isRecord,
  records,
  trimmed,
  type Pair,
  type Row,
} from './values';

/* Counts concern recorded launches; unpaired and activity concern this parent's own launches. An unread
   child is never a completed job. */
export interface DelegatedWork {
  /** Whether the line is worth drawing: a launch was recorded, or its time was. */
  readonly draw: boolean;
  /** An unpaired launch and half an hour of recorded silence. */
  readonly risky: boolean;
  readonly text: string;
}

const QUIET_AFTER_SECONDS = 1800;

/* `now` is the payload's clock, or null where it published none, which reads every launch as not yet
   quiet: `quiet <= null` is `quiet <= 0` in the legacy page, so a missing clock never manufactures a
   quiet period. */
export function delegatedWork(session: Row | null | undefined, now: number | null): DelegatedWork {
  const count = session?.['delegated_launches'];
  const unpaired = session?.['delegated_unpaired'];
  const visibility = String(session?.['delegated_visibility'] || 'not-recorded');
  const measured =
    Number.isInteger(count) &&
    (count as number) >= 0 &&
    Number.isInteger(unpaired) &&
    (unpaired as number) >= 0;
  if (!measured) {
    return {
      draw: (nextNumber(session?.['delegated_latest_launch_at']) ?? 0) > 0,
      risky: false,
      text: 'Delegated work: not measured; Compass cannot see work this session started.',
    };
  }
  const launches = count as number;
  const open = unpaired as number;
  const latest = nextNumber(session?.['delegated_latest_launch_at']) ?? 0;
  const activity = nextNumber(session?.['delegated_last_activity_at']) ?? 0;
  const quiet = nextNumber(session?.['delegated_quiet_since']) ?? 0;
  const age = quiet > 0 && quiet <= (now ?? 0) ? (now ?? 0) - quiet : null;
  const risky = open > 0 && age !== null && age >= QUIET_AFTER_SECONDS;
  const limit = ['partial', 'unattributed', 'not-recorded'].includes(visibility)
    ? ' Compass cannot see all work this session started.'
    : '';
  const times =
    (latest > 0 ? ` Latest launch ${clock(latest)}.` : '') +
    (activity > 0 ? ` Last recorded activity ${clock(activity)}.` : '');
  const quietText =
    risky && age !== null
      ? ` Nothing recorded for ${String(Math.floor(age / 60))} minutes. A server left running can also show here.`
      : '';
  return {
    draw: launches > 0,
    risky,
    text:
      `Delegated work: ${String(launches)} recorded launch${launches === 1 ? '' : 'es'}; ` +
      `${String(open)} of this session's launches ${open === 1 ? 'has' : 'have'} no recorded completion.${times}${quietText}${limit}`,
  };
}

/* The harnesses whose turn stop a reader may have analyzed, spelt once on this side: the server's
   `reading.TURN_STOP_HARNESSES` is the same list, and the legacy page's test compares the two. */
export const READING_TURN_STOP_HARNESSES: readonly string[] = ['claude'];

export interface SessionStop {
  readonly at: number;
  readonly kind: 'hook' | 'transcript';
}

/* The turn stop a row rests on: the hook's when held, else the stop Claude Code's transcript records on
   a harness read at a turn stop. The Close section and the observed-stops count read `finished_at`
   alone, because they count what was observed. */
export function sessionStop(source: Row | null | undefined): SessionStop | null {
  const hook = nextNumber(source?.['finished_at']);
  if (hook !== null && hook > 0) return { at: hook, kind: 'hook' };
  const recorded = nextNumber(source?.['turn_end_at']);
  if (
    READING_TURN_STOP_HARNESSES.includes(String(source?.['harness'] || '')) &&
    recorded !== null &&
    recorded > 0
  ) {
    return { at: recorded, kind: 'transcript' };
  }
  return null;
}

/* How it landed, as two axes that never merge. Axis one is what ended: four kinds and a running row,
   because the three ways a session can be silent are not one fact (a turn stopped, a session ended, and
   idle-with-nothing-observed all read as "quiet", and only the first two authorise anything). The fourth
   is the scan-only row, where the silence belongs to the harness rather than to the session. Axis two is
   who says it finished, and today the honest answer is always the session itself: both stamps originate in
   the harness the agent runs inside, and the one independent observer, the end-of-session git probe, sees
   a working tree and not a deliverable. So `independent` is a limit line, never a branch. */
export type EndKind = 'session-end' | 'turn-stop' | 'running' | 'unobservable' | 'idle-unknown';

export type Landing = {
  readonly endKind: EndKind;
  readonly claimKind: 'agent' | 'none';
} & Pair<'end'> &
  Pair<'claim'> &
  Pair<'independent'>;

/* `stopped` is `sessionStop`'s answer, or any truthy value for a hook stop. A transcript stop is named
   as the transcript's: Compass read it from Claude Code's own record rather than observing it. */
export function landingOf(
  source: Row,
  ended: boolean,
  stopped: SessionStop | boolean | null,
): Landing {
  const idle = source['state'] === 'idle';
  const endKind: EndKind = ended
    ? 'session-end'
    : stopped && idle
      ? 'turn-stop'
      : !idle
        ? 'running'
        : isScanOnly(source)
          ? 'unobservable'
          : 'idle-unknown';
  const recorded = typeof stopped === 'object' && stopped !== null && stopped.kind === 'transcript';
  const endText =
    endKind === 'session-end'
      ? 'A session end was observed'
      : endKind === 'turn-stop'
        ? recorded
          ? "Claude Code's transcript shows the last turn finished; no session end was observed"
          : 'A turn stop was observed; no session end was'
        : '';
  const endWhy =
    endKind === 'idle-unknown'
      ? 'Idle with completion unknown: no stop and no end was observed'
      : endKind === 'unobservable'
        ? 'No event from this harness can reach this row, so no stop or end can be observed'
        : 'No stop or end observed while the session is running';
  const claimed = ended || Boolean(stopped);
  const changed =
    Number.isInteger(source['changed']) && (source['changed'] as number) >= 0
      ? (source['changed'] as number)
      : null;
  const independent =
    source['dirty'] === true
      ? `${changed === null ? 'Uncommitted work was' : `${String(changed)} changed ${changed === 1 ? 'entry was' : 'entries were'}`} observed, ` +
        'which shows work happened and not that the requested output exists'
      : source['dirty'] === false
        ? 'The working tree was observed clean, which is not evidence a deliverable exists'
        : "Git state was not measured, so nothing was observed apart from the session's own account";
  return {
    endKind,
    ...pair('end', endText, endWhy),
    claimKind: claimed ? 'agent' : 'none',
    ...pair(
      'claim',
      claimed ? 'The agent reported it finished' : '',
      'Nothing has claimed this session finished',
    ),
    // Deliberately never known. The true arm arrives with a source that sees a deliverable without the
    // session's account; until then the reader is told why, rather than shown a blank.
    ...pair('independent', '', independent),
  };
}

/* What an analysis will read, said before the press, from the same end kind HOW IT LANDED shows so the
   two cannot disagree. Empty where the server would withhold whatever was pressed: an idle row with no
   stop or end, or a turn stop, on a harness it does not read there. A running session is read mid-flight
   and says so, so a press on it never reads as a final one. An idle Claude Code row with no recorded stop
   or end is read the same way up to its last recorded entry (owner, 2026-10-20), and says that too. */
export function readHint(source: Row): string {
  const ended = endedAt(source) !== null;
  const stopped = source['state'] === 'idle' ? sessionStop(source) : null;
  const kind = landingOf(source, ended, stopped).endKind;
  if (kind === 'running') return 'Reads the work so far; the session is still running.';
  const turnStops = READING_TURN_STOP_HARNESSES.includes(String(source['harness'] || ''));
  if ((kind === 'idle-unknown' || kind === 'unobservable') && turnStops)
    return 'Reads the session up to its last recorded entry; its last turn was not recorded as finished.';
  const cutoff =
    kind === 'session-end'
      ? 'its end'
      : kind === 'turn-stop'
        ? turnStops
          ? 'its last turn'
          : ''
        : '';
  return cutoff ? `Reads the session up to ${cutoff} against your intent.` : '';
}

export interface Goal {
  readonly text: string;
  readonly src: string;
  /** The observation time, carried rather than derived: the workflow arm has none, and a render that
      timestamped both would date the second from whenever the page last drew. */
  readonly at: number | null;
}

/* This session's own derived goal: the latest assignment it was asked, else the goals of its Spacedock
   workflows. `false` is none, which the model words as an absence. */
export function goalOf(source: Row): Goal | false {
  const instruction = source['instruction'];
  if (
    isRecord(instruction) &&
    instruction['label'] === 'asked' &&
    trimmed(instruction['text']) &&
    !promptCopied(source, 'instruction')
  ) {
    return {
      text: instruction['text'] as string,
      src: `${String(source['harness'])} · latest instruction`,
      at: nextNumber(instruction['at']),
    };
  }
  const spacedock = source['spacedock'];
  const workflows = records(isRecord(spacedock) ? spacedock['workflows'] : undefined);
  const goals = workflows.filter((workflow) => trimmed(workflow['goal']));
  return goals.length
    ? {
        text: goals.map((workflow) => String(workflow['goal'])).join('\n'),
        src: 'Spacedock · workflow goal',
        at: null,
      }
    : false;
}

export interface SessionDot {
  readonly className: string;
  readonly tone: string;
  readonly label: string;
  readonly shape: 'ended' | 'quiet' | 'filled';
  readonly pulse: boolean;
}

/* One dot per member line. Its SHAPE carries the lifecycle, so the three read apart in greyscale and
   without the pulse: working and blocked are filled whatever their tone, quiet is a ring, ended is
   square. A quiet ring drops only the `ok` accent; a quiet session carrying a risk keeps its colour, and
   one holding an exact request is blocked rather than quiet. */
export function sessionDot(session: {
  readonly isEnded: boolean;
  readonly isQuiet: boolean;
  readonly askKnown: boolean;
  readonly isLive: boolean;
  readonly tone: string;
  readonly state: string;
}): SessionDot {
  const shape = session.isEnded
    ? 'ended'
    : session.isQuiet && !session.askKnown
      ? 'quiet'
      : 'filled';
  const shapeClass =
    shape === 'ended'
      ? ' next-project-dot--ended'
      : shape === 'quiet'
        ? ' next-project-dot--quiet'
        : ' next-project-dot--filled';
  const pulse = session.isLive ? ' next-project-dot--working' : '';
  return {
    className: `next-project-dot next-project-tone--${session.tone}${shapeClass}${pulse}`,
    tone: session.tone,
    label: session.state,
    shape,
    pulse: session.isLive,
  };
}
