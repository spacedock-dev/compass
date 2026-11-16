import { locationWarnings } from '../observed/location';
import { nextNumber } from '../api/bootstrap';
import {
  delegatedWork,
  endedAt,
  exactAskOwner,
  gapNames,
  isRecord,
  nativeSession,
  payloadAskRows,
  payloadSessionRows,
  sessionKey,
  type Row,
} from '../observed';
import { asPayload } from '../observed/values';

/* What the board asks of the reader, as subjects in four queues: a question or a reported block (NEEDS
   YOU), a risk, a session that ended or stopped and wants closing, and a published task coming next. The
   legacy page's `nextAttentionModel`, ported function for function and held to it by the differential
   test, because the order of these queues is the product: an ordering that drifts is a different
   judgement about what comes first. Everything here is a pure reading of one payload. Nothing reads the
   clock, the DOM or storage, and nothing is invented: a subject exists because the board published the
   thing that makes it one, and a lower-priority signal stays attached to the subject that outranks it
   rather than being dropped. */

export type Section = 'needs' | 'risk' | 'close' | 'next';

export interface Detail {
  readonly ask?: Row;
  readonly owner?: Row;
  readonly session?: Row;
  readonly task?: Row;
  readonly errors?: number;
  readonly failures?: number;
  readonly barren?: boolean;
  readonly tool?: string;
  readonly harness?: string;
  readonly scope?: string;
  readonly pct?: number;
  readonly resetAt?: number | null;
  readonly reason?: string;
  readonly paceRatio?: number | null;
  readonly endsInSec?: number | null;
  readonly tone?: string;
  readonly finishedAt?: number | null;
  readonly endedAt?: number | null;
  readonly dirty?: boolean | null;
  readonly changed?: number | null;
  readonly changedEntries?: number | null;
  readonly state?: string;
  readonly active?: boolean;
  readonly label?: string;
  readonly memberCount?: number;
  readonly text?: string;
}

export interface Signal {
  readonly kind: string;
  readonly section: Section;
  readonly sourceIndex: number;
  readonly detail: Detail;
}

export interface Identity {
  readonly harness: string;
  readonly project: string;
  readonly sid: string;
}

export interface Checkpoint {
  readonly status?: unknown;
  readonly activeForm?: unknown;
  readonly subject?: unknown;
  readonly resetAt?: number;
}

export interface Subject {
  readonly key: string;
  readonly stableId?: string;
  readonly kind: 'ask' | 'session' | 'quota' | 'collision';
  readonly section: Section;
  primaryKind: string;
  signals: Signal[];
  readonly session: Row | null;
  readonly sessions: readonly Row[];
  readonly asks: Row[];
  sourceIndex: number;
  readonly responsibility?: string;
  checkpoint?: Checkpoint;
  readonly identity?: Identity;
  readonly memberKeys?: readonly string[];
}

export interface Coverage {
  readonly gates: {
    readonly discovered: number;
    readonly reporting: number;
    readonly unknown: number;
    readonly failed: number;
    readonly rows: readonly Row[];
  };
  readonly exactRequestsReported: boolean;
  readonly exactRequestCount: number;
  readonly rates: {
    readonly reported: number;
    readonly notReported: number;
    readonly failed: number;
    readonly rows: readonly Row[];
  };
  readonly observedStops: number;
  readonly observedEnds: number;
}

export interface Healthy {
  readonly sessions: readonly Row[];
  readonly moving: number;
  readonly quiet: number;
  readonly unknown: number;
  readonly partial: number;
}

export interface AttentionModel {
  readonly needs: readonly Subject[];
  readonly risk: readonly Subject[];
  readonly close: readonly Subject[];
  readonly next: readonly Subject[];
  readonly healthy: Healthy;
  readonly coverage: Coverage;
  readonly counts: {
    readonly needs: number;
    readonly risk: number;
    readonly close: number;
    readonly next: number;
    readonly moving: number;
    readonly quiet: number;
    readonly unknown: number;
  };
  readonly harnessOrder: readonly string[];
  readonly representedSessionKeys: readonly string[];
  readonly generated: number | null;
  readonly windowHours: number | null;
  readonly sessionCount: number;
}

const text = (value: unknown): string => String(value == null ? '' : value);

function askAge(ask: Row): number | null {
  const age = nextNumber(ask['age_sec']);
  return age !== null && age >= 0 ? age : null;
}

function askKey(ask: Row, sourceIndex: number): string {
  return ask['id'] != null ? `ask:${String(ask['id'])}` : `ask-index:${String(sourceIndex)}`;
}

function harnessOrderOf(payload: Row): string[] {
  if (!Array.isArray(payload['harnesses'])) return [];
  const found: string[] = [];
  for (const harness of payload['harnesses'] as unknown[]) {
    const key = String((isRecord(harness) && harness['key']) || '');
    if (key && !found.includes(key)) found.push(key);
  }
  return found;
}

const RISK_ORDER = new Map<string, number>([
  ['attribution', 0],
  ['loop', 1],
  ['quota', 2],
  ['long-turn', 3],
  ['collision', 4],
  ['checkout', 4],
  ['quiet-launch', 5],
]);

/* What is at stake leads and the end breaks its ties: uncommitted work is the reason to open the row at
   all, and an ended session's dirty tree is the one nobody is coming back to. */
const STOP_ORDER = new Map<string, number>([
  ['end-dirty', 0],
  ['stop-dirty', 1],
  ['end-unknown', 2],
  ['stop-unknown', 3],
  ['end-clean', 4],
  ['stop-clean', 5],
]);

/* A kind the list does not know sorts as a collision, which is where the legacy page puts a stop signal
   riding on a risk subject: it never ranks above a risk the board measured. */
function riskKind(signal: Signal | undefined): string {
  return signal && RISK_ORDER.has(signal.kind) ? signal.kind : 'collision';
}

function riskRank(signal: Signal | undefined): number {
  return RISK_ORDER.get(riskKind(signal)) as number;
}

export function subjectIdentity(subject: Subject | { readonly session: Row | null }): Row | null {
  if ('identity' in subject && subject.identity) return subject.identity as unknown as Row;
  if (subject.session) return subject.session;
  const sessions = 'sessions' in subject ? subject.sessions : null;
  return Array.isArray(sessions) ? ((sessions[0] as Row | undefined) ?? null) : null;
}

interface Comparator {
  readonly generated: number | null;
  readonly harnessOrder: readonly string[];
}

function compareText(one: unknown, two: unknown): number {
  return text(one).localeCompare(text(two), 'en');
}

function stableCompare(left: Subject, right: Subject, model: Comparator): number {
  const leftSession = subjectIdentity(left);
  const rightSession = subjectIdentity(right);
  const order = new Map(model.harnessOrder.map((harness, index) => [harness, index]));
  const harnessIndex = (session: Row | null): number => {
    const key = String((session && session['harness']) || '');
    return order.has(key) ? (order.get(key) as number) : Number.MAX_SAFE_INTEGER;
  };
  const leftHarness = harnessIndex(leftSession);
  const rightHarness = harnessIndex(rightSession);
  if (leftHarness !== rightHarness) return leftHarness - rightHarness;
  const project = compareText(leftSession?.['project'], rightSession?.['project']);
  if (project) return project;
  const sid = compareText(leftSession?.['sid'], rightSession?.['sid']);
  if (sid) return sid;
  const leftIndex = Number.isInteger(left.sourceIndex) ? left.sourceIndex : Number.MAX_SAFE_INTEGER;
  const rightIndex = Number.isInteger(right.sourceIndex)
    ? right.sourceIndex
    : Number.MAX_SAFE_INTEGER;
  if (leftIndex !== rightIndex) return leftIndex - rightIndex;
  return compareText(left.stableId || left.key, right.stableId || right.key);
}

/* The age of a payload stamp against the payload's own clock, so a subject ages only when a new board
   arrives. */
function ageAt(generated: number | null, stamp: unknown): number | null {
  const at = nextNumber(stamp);
  if (generated === null || at === null || at <= 0) return null;
  return Math.max(0, generated - at);
}

export function subjectAge(subject: Subject, generated: number | null): number | null {
  if (subject.primaryKind === 'ask') {
    const ages = subject.asks.map(askAge).filter((age): age is number => age !== null);
    return ages.length ? Math.max(...ages) : null;
  }
  if (subject.primaryKind === 'input') return ageAt(generated, subject.session?.['blocked_since']);
  if (subject.section === 'close') {
    return ageAt(generated, subject.signals[0]?.detail.finishedAt);
  }
  return null;
}

function compareSubjects(left: Subject, right: Subject, model: Comparator): number {
  const kindOrder: Record<string, number> = { ask: 0, input: 1 };
  const leftKind = kindOrder[left.primaryKind] ?? 2;
  const rightKind = kindOrder[right.primaryKind] ?? 2;
  if (leftKind !== rightKind) return leftKind - rightKind;
  if (left.primaryKind === 'ask' && right.primaryKind === 'ask') {
    const leftAge = Math.max(
      ...left.asks.map(askAge).filter((age): age is number => age !== null),
      -1,
    );
    const rightAge = Math.max(
      ...right.asks.map(askAge).filter((age): age is number => age !== null),
      -1,
    );
    if (leftAge !== rightAge) return rightAge - leftAge;
    if (leftAge >= 0 && left.sourceIndex !== right.sourceIndex) {
      return left.sourceIndex - right.sourceIndex;
    }
  }
  if (left.primaryKind === 'input' && right.primaryKind === 'input') {
    const leftAge = ageAt(model.generated, left.session?.['blocked_since']);
    const rightAge = ageAt(model.generated, right.session?.['blocked_since']);
    if (leftAge !== null && rightAge === null) return -1;
    if (leftAge === null && rightAge !== null) return 1;
    if (leftAge !== null && rightAge !== null && leftAge !== rightAge) return rightAge - leftAge;
  }
  if (left.section === 'close' && right.section === 'close') {
    const leftStop = STOP_ORDER.get(left.primaryKind) as number;
    const rightStop = STOP_ORDER.get(right.primaryKind) as number;
    if (leftStop !== rightStop) return leftStop - rightStop;
    const leftFinished = left.signals[0]?.detail.finishedAt ?? null;
    const rightFinished = right.signals[0]?.detail.finishedAt ?? null;
    if (leftFinished !== rightFinished) return (leftFinished ?? 0) - (rightFinished ?? 0);
  }
  if (left.section === 'next' && right.section === 'next') {
    const leftStatusOrder = left.checkpoint?.status === 'in_progress' ? 0 : 1;
    const rightStatusOrder = right.checkpoint?.status === 'in_progress' ? 0 : 1;
    if (leftStatusOrder !== rightStatusOrder) return leftStatusOrder - rightStatusOrder;
    const leftWorking = left.session?.['state'] === 'working';
    const rightWorking = right.session?.['state'] === 'working';
    const leftIdle = left.session?.['state'] === 'idle';
    const rightIdle = right.session?.['state'] === 'idle';
    if (leftWorking && rightIdle) return -1;
    if (leftIdle && rightWorking) return 1;
  }
  if (left.section === 'risk' && right.section === 'risk') {
    const leftSignal = left.signals[0] as Signal;
    const rightSignal = right.signals[0] as Signal;
    const leftRisk = riskKind(leftSignal);
    const rightRisk = riskKind(rightSignal);
    const byKind = (RISK_ORDER.get(leftRisk) as number) - (RISK_ORDER.get(rightRisk) as number);
    if (byKind) return byKind;
    const leftDetail = leftSignal.detail;
    const rightDetail = rightSignal.detail;
    if (leftRisk === 'attribution' && left.sourceIndex !== right.sourceIndex) {
      return left.sourceIndex - right.sourceIndex;
    }
    if (leftRisk === 'loop') {
      // The turn total ranks these, not the peak run: a turn that failed six times with a success in
      // the middle is worse off than one that failed four in a row, and ordering by the peak put it
      // second.
      const leftTotal = (leftDetail.failures ?? leftDetail.errors) as number;
      const rightTotal = (rightDetail.failures ?? rightDetail.errors) as number;
      if (leftTotal !== rightTotal) return rightTotal - leftTotal;
      if (leftDetail.errors !== rightDetail.errors) {
        return (rightDetail.errors as number) - (leftDetail.errors as number);
      }
    }
    if (leftRisk === 'quota') {
      if (leftDetail.pct !== rightDetail.pct) {
        return (rightDetail.pct as number) - (leftDetail.pct as number);
      }
      const leftReset = leftDetail.resetAt ?? null;
      const rightReset = rightDetail.resetAt ?? null;
      if (leftReset !== null && rightReset === null) return -1;
      if (leftReset === null && rightReset !== null) return 1;
      if (leftReset !== null && rightReset !== null && leftReset !== rightReset) {
        return leftReset - rightReset;
      }
    }
    if (leftRisk === 'collision' && leftDetail.memberCount !== rightDetail.memberCount) {
      return (rightDetail.memberCount as number) - (leftDetail.memberCount as number);
    }
  }
  return stableCompare(left, right, model);
}

function loopSignal(session: Row, sourceIndex: number): Signal | null {
  const loop = session['loop'];
  if (!isRecord(loop) || !Number.isInteger(loop['errors']) || (loop['errors'] as number) <= 0) {
    return null;
  }
  const errors = loop['errors'] as number;
  // `errors` is the peak consecutive run and `failures` the turn total, which no success resets. They
  // differ exactly when a success split the failures, which is the case the run alone reads as clean.
  const failures = Number.isInteger(loop['failures']) ? (loop['failures'] as number) : null;
  const tool = typeof loop['tool'] === 'string' ? loop['tool'].trim() : '';
  const detail: Detail = {
    errors,
    ...(failures !== null && failures > errors ? { failures } : {}),
    ...(loop['barren'] === true ? { barren: true } : {}),
    ...(tool ? { tool } : {}),
  };
  return { kind: 'loop', section: 'risk', sourceIndex, detail };
}

function longTurnSignal(session: Row, sourceIndex: number): Signal | null {
  session = nativeSession(session);
  const turn = session['turn'];
  if (session['state'] === 'working' && isRecord(turn) && turn['long'] === true) {
    return { kind: 'long-turn', section: 'risk', sourceIndex, detail: { session } };
  }
  return null;
}

/* Two floors, and a pace may raise a row only above both. Early in a window the ratio is arithmetic on
   almost no time: 5% spent with 1% elapsed is a five-times pace and means nothing, and a signal firing
   on that noise teaches the reader to ignore the one that matters.

   A tenth of the window is the time floor. A quarter was tried first and was wrong, because it excluded
   the case this trigger exists for: a five-hour window a third spent with an eighth of its time gone is
   36 real minutes and 34 real points, and it runs dry three hours before it resets.

   Ten points is the budget floor, and it bounds rounding rather than time. `pct` is an integer, so at
   two points one point of rounding is half the ratio; at ten it is a tenth. */
const QUOTA_PACE_MIN_ELAPSED = 0.1;
const QUOTA_PACE_MIN_PCT = 10;

interface QuotaPace {
  readonly elapsed: number;
  readonly ratio: number;
  readonly remainingSec: number;
  readonly endsInSec: number | null;
}

/* The window's own average pace and where it lands, or null when the vendor did not publish enough to
   say. Both inputs come from one response, so this composes nothing: `windowSec` is the slot's length
   and `resetAt` its end. */
function quotaPace(row: Row, generated: unknown): QuotaPace | null {
  const windowSec = nextNumber(row['windowSec']);
  const resetAt = nextNumber(row['resetAt']);
  const at = nextNumber(generated);
  if (windowSec === null || windowSec <= 0 || resetAt === null || at === null) return null;
  const remainingSec = resetAt - at;
  const elapsed = Math.max(0, Math.min(1, (windowSec - remainingSec) / windowSec));
  if (elapsed <= 0) return null;
  const pct = row['pct'] as number;
  const perMin = pct / ((elapsed * windowSec) / 60);
  return {
    elapsed,
    ratio: pct / (elapsed * 100),
    remainingSec,
    // A pace of zero is not "ends never" in any useful sense, but it is honestly "not projected".
    endsInSec: perMin > 0 ? ((100 - pct) / perMin) * 60 : null,
  };
}

function quotaSignal(
  entry: Row,
  scope: string,
  row: unknown,
  sourceIndex: number,
  generated: unknown,
): Signal | null {
  if (entry['state'] !== 'ok' || !isRecord(row) || !Number.isInteger(row['pct'])) return null;
  const pct = row['pct'] as number;
  const pace = quotaPace(row, generated);
  /* Two triggers, and the level one is unchanged because it is proven and it catches what pace cannot
     see. Pace adds the case the level misses entirely: a window a third spent with an eighth of its time
     gone runs dry hours before it resets, while a window at 88% with 91% elapsed finishes the period
     with room to spare. */
  const byLevel = pct >= 70;
  const byPace =
    pace !== null &&
    pace.elapsed >= QUOTA_PACE_MIN_ELAPSED &&
    pct >= QUOTA_PACE_MIN_PCT &&
    pace.endsInSec !== null &&
    pace.remainingSec > 0 &&
    pace.endsInSec < pace.remainingSec;
  if (!byLevel && !byPace) return null;
  const reset = row['resetAt'];
  const resetAt = typeof reset === 'number' && Number.isFinite(reset) && reset > 0 ? reset : null;
  return {
    kind: 'quota',
    section: 'risk',
    sourceIndex,
    detail: {
      harness: String(entry['harness'] || ''),
      scope,
      pct,
      resetAt,
      reason: byLevel ? 'level' : 'pace',
      paceRatio: pace === null ? null : pace.ratio,
      endsInSec: pace === null ? null : pace.endsInSec,
      tone: pct >= 90 || (byPace && !byLevel) ? 'critical' : 'warning',
    },
  };
}

function quotaSignalCompare(left: Signal, right: Signal): number {
  const leftDetail = left.detail;
  const rightDetail = right.detail;
  if (leftDetail.pct !== rightDetail.pct) {
    return (rightDetail.pct as number) - (leftDetail.pct as number);
  }
  const leftReset = leftDetail.resetAt ?? null;
  const rightReset = rightDetail.resetAt ?? null;
  if (leftReset !== null && rightReset === null) return -1;
  if (leftReset === null && rightReset !== null) return 1;
  if (leftReset !== null && rightReset !== null && leftReset !== rightReset) {
    return leftReset - rightReset;
  }
  return left.sourceIndex - right.sourceIndex;
}

function attributionSignal(session: Row, sourceIndex: number): Signal | null {
  session = nativeSession(session);
  const finishedAt = nextNumber(session['finished_at']);
  const validFinishedAt = finishedAt !== null && finishedAt > 0;
  const publishedGit =
    typeof session['dirty'] === 'boolean' || Number.isInteger(session['changed']);
  const active = session['state'] === 'working' || session['active'] === true;
  if ((publishedGit && !validFinishedAt) || (validFinishedAt && active)) {
    return {
      kind: 'attribution',
      section: 'risk',
      sourceIndex,
      detail: {
        finishedAt: validFinishedAt ? finishedAt : null,
        dirty: typeof session['dirty'] === 'boolean' ? session['dirty'] : null,
        changed: Number.isInteger(session['changed']) ? (session['changed'] as number) : null,
        state: text(session['state'] || ''),
        active: session['active'] === true,
      },
    };
  }
  return null;
}

function stopSignal(session: Row, sourceIndex: number): Signal | null {
  session = nativeSession(session);
  const ended = endedAt(session);
  const finishedAt = session['finished_at'];
  const finished = typeof finishedAt === 'number' && Number.isFinite(finishedAt) && finishedAt > 0;
  /* An observed end promotes the row on its own, and deliberately does not have to agree with `state`:
     `state` is a collector inference off file recency, an end is an event the session reported, and
     requiring both would let the weaker reading veto the stronger one. A stop still needs the idle state
     beside it, because a stop leaves the session open and typeable and the state is the only thing that
     says it stayed that way. */
  if (ended === null && (!finished || session['state'] !== 'idle')) return null;
  const prefix = ended === null ? 'stop' : 'end';
  let kind = `${prefix}-unknown`;
  if (session['dirty'] === true) kind = `${prefix}-dirty`;
  if (session['dirty'] === false) kind = `${prefix}-clean`;
  const changed = session['changed'];
  return {
    kind,
    section: 'close',
    sourceIndex,
    detail: {
      finishedAt: finished ? (finishedAt as number) : null,
      endedAt: ended,
      changedEntries:
        Number.isInteger(changed) && (changed as number) >= 0 ? (changed as number) : null,
    },
  };
}

function coverageOf(payload: Row): Coverage {
  const rows = Array.isArray(payload['harnesses']) ? (payload['harnesses'] as unknown[]) : [];
  const discovered = rows.filter((row): row is Row => isRecord(row) && row['discovered'] === true);
  const clean = discovered.filter((row) => row['error'] == null);
  const sessions = payloadSessionRows(payload);
  const stamped = (session: Row) => {
    const finished = session['finished_at'];
    return typeof finished === 'number' && Number.isFinite(finished) && finished > 0;
  };
  return {
    gates: {
      discovered: discovered.length,
      reporting: clean.filter((row) => row['reports_needs_input'] === true).length,
      unknown: clean.filter((row) => row['reports_needs_input'] !== true).length,
      failed: discovered.filter((row) => row['error'] != null).length,
      rows: discovered,
    },
    exactRequestsReported: payload['ask'] === true,
    exactRequestCount: payloadAskRows(payload).length,
    rates: {
      reported: clean.filter((row) => row['reports_rate'] === true).length,
      notReported: clean.filter((row) => row['reports_rate'] === false).length,
      failed: discovered.filter((row) => row['error'] != null).length,
      rows: discovered,
    },
    observedStops: sessions.filter(stamped).length,
    observedEnds: sessions.filter((session) => endedAt(session) !== null).length,
  };
}

/* The first in-progress task, else the first pending one: the one checkpoint a session publishes. */
export function publishedTask(session: Row | null): Row | null {
  const tasks = session && Array.isArray(session['tasks']) ? (session['tasks'] as unknown[]) : [];
  const valid = tasks.filter(isRecord);
  return (
    valid.find((task) => task['status'] === 'in_progress') ??
    valid.find((task) => task['status'] === 'pending') ??
    null
  );
}

function responsibilityOf(payload: Row, ask: Row): string {
  const owner = exactAskOwner(payload, ask);
  return owner && isRecord(owner['spacedock']) ? 'CAPTAIN' : 'NEEDS YOU';
}

export function attentionModel(input: unknown): AttentionModel {
  const payload = asPayload(input);
  const sessions = payloadSessionRows(payload);
  const asks = payloadAskRows(payload);
  const subjects = new Map<string, Subject>();
  const riskSubjects = new Map<string, Subject>();
  const matchedAskOwners = new Set<string>();

  for (const [sourceIndex, ask] of asks.entries()) {
    if (!text(ask['question']).trim()) continue;
    const owner = exactAskOwner(payload, ask);
    if (!owner) {
      const subject: Subject = {
        key: askKey(ask, sourceIndex),
        kind: 'ask',
        section: 'needs',
        primaryKind: 'ask',
        signals: [{ kind: 'ask', section: 'needs', detail: { ask }, sourceIndex }],
        session: null,
        sessions: [],
        asks: [ask],
        sourceIndex,
        responsibility: 'NEEDS YOU',
      };
      subjects.set(subject.key, subject);
      continue;
    }
    const key = sessionKey(owner);
    let subject = subjects.get(key);
    if (!subject) {
      const created: Subject = {
        key,
        kind: 'session',
        section: 'needs',
        primaryKind: 'ask',
        signals: [],
        session: owner,
        sessions: [owner],
        asks: [],
        sourceIndex,
        responsibility: responsibilityOf(payload, ask),
      };
      const checkpoint = publishedTask(owner);
      if (checkpoint) created.checkpoint = checkpoint;
      subjects.set(key, created);
      subject = created;
    }
    subject.asks.push(ask);
    subject.signals.push({ kind: 'ask', section: 'needs', detail: { ask }, sourceIndex });
    const askProject = text(ask['project']).trim();
    if (askProject && askProject !== text(owner['project'])) {
      subject.signals.push({
        kind: 'attribution',
        section: 'needs',
        detail: { ask, owner },
        sourceIndex,
      });
    }
    matchedAskOwners.add(key);
  }

  for (const [sourceIndex, session] of sessions.entries()) {
    const key = sessionKey(session);
    if (session['state'] !== 'needs_input' || matchedAskOwners.has(key)) continue;
    const subject: Subject = {
      key,
      kind: 'session',
      section: 'needs',
      primaryKind: 'input',
      signals: [{ kind: 'input', section: 'needs', detail: { session }, sourceIndex }],
      session,
      sessions: [session],
      asks: [],
      sourceIndex,
    };
    const checkpoint = publishedTask(session);
    if (checkpoint) subject.checkpoint = checkpoint;
    subjects.set(key, subject);
  }

  const addSessionRisk = (session: Row, signal: Signal | null, sourceIndex: number): void => {
    if (!signal) return;
    const key = sessionKey(session);
    const needsSubject = subjects.get(key);
    if (needsSubject && needsSubject.section === 'needs') {
      needsSubject.signals.push({ ...signal, section: 'needs' });
      return;
    }
    let subject = riskSubjects.get(key);
    if (!subject) {
      subject = {
        key,
        stableId: key,
        kind: 'session',
        section: 'risk',
        primaryKind: signal.kind,
        signals: [],
        session,
        sessions: [session],
        asks: [],
        sourceIndex,
      };
      riskSubjects.set(key, subject);
    }
    subject.signals.push(signal);
    subject.signals.sort((left, right) => riskRank(left) - riskRank(right));
    subject.primaryKind = (subject.signals[0] as Signal).kind;
    subject.sourceIndex = (subject.signals[0] as Signal).sourceIndex;
  };

  const generated = nextNumber(payload['generated']);
  for (const [sourceIndex, session] of sessions.entries()) {
    addSessionRisk(session, attributionSignal(session, sourceIndex), sourceIndex);
    addSessionRisk(session, loopSignal(session, sourceIndex), sourceIndex);
    addSessionRisk(session, longTurnSignal(session, sourceIndex), sourceIndex);
    const delegated = delegatedWork(session, generated);
    if (delegated.risky) {
      addSessionRisk(
        session,
        { kind: 'quiet-launch', section: 'risk', sourceIndex, detail: { text: delegated.text } },
        sourceIndex,
      );
    }
  }

  const usage = Array.isArray(payload['usage']) ? (payload['usage'] as unknown[]) : [];
  for (const [usageIndex, entry] of usage.entries()) {
    if (!isRecord(entry)) continue;
    const harness = String(entry['harness'] || '');
    const addQuota = (scope: string, row: unknown, sourceIndex: number): void => {
      const signal = quotaSignal(entry, scope, row, sourceIndex, payload['generated']);
      if (!signal) return;
      const key = `quota:${harness}:${scope}`;
      let subject = riskSubjects.get(key);
      if (!subject) {
        subject = {
          key,
          stableId: scope,
          kind: 'quota',
          section: 'risk',
          primaryKind: 'quota',
          signals: [],
          session: null,
          sessions: [],
          asks: [],
          sourceIndex,
          identity: { harness, project: scope, sid: '' },
        };
        riskSubjects.set(key, subject);
      }
      subject.signals.push(signal);
      subject.signals.sort(quotaSignalCompare);
      const first = subject.signals[0] as Signal;
      subject.sourceIndex = first.sourceIndex;
      if (first.detail.resetAt != null) {
        subject.checkpoint = { resetAt: first.detail.resetAt };
      } else {
        delete subject.checkpoint;
      }
    };
    for (const scope of ['fiveH', 'week', 'month']) addQuota(scope, entry[scope], usageIndex);
    const models = Array.isArray(entry['models']) ? (entry['models'] as unknown[]) : [];
    for (const [modelIndex, row] of models.entries()) {
      const label = isRecord(row) && typeof row['label'] === 'string' ? row['label'] : '';
      addQuota(`model:${label}:${String(modelIndex)}`, row, usageIndex);
    }
  }

  const labels = new Map<string, Map<string, { session: Row; sourceIndex: number }>>();
  for (const [sourceIndex, session] of sessions.entries()) {
    const project = session['project'];
    const label = typeof project === 'string' && project.trim() ? project : '';
    if (!label) continue;
    let members = labels.get(label);
    if (!members) {
      members = new Map();
      labels.set(label, members);
    }
    const key = sessionKey(session);
    if (!members.has(key)) members.set(key, { session, sourceIndex });
  }
  const harnessOrder = harnessOrderOf(payload);
  for (const [label, members] of labels) {
    const memberRows = [...members.values()];
    for (const warning of locationWarnings(memberRows.map((row) => row.session))) {
      const key = `${warning.kind}:${label}`;
      const lowest = Math.min(...memberRows.map((row) => row.sourceIndex));
      riskSubjects.set(key, {
        key,
        stableId: key,
        kind: 'collision',
        section: 'risk',
        primaryKind: warning.kind,
        signals: [
          {
            kind: warning.kind,
            section: 'risk',
            sourceIndex: lowest,
            detail: { label, memberCount: warning.members.length, text: warning.text },
          },
        ],
        session: null,
        sessions: [...warning.members],
        asks: [],
        sourceIndex: lowest,
        identity: { harness: '', project: label, sid: '' },
      });
    }
  }

  const riskRepresented = new Set<string>();
  for (const subject of riskSubjects.values()) {
    if (subject.kind === 'collision') continue;
    for (const memberKey of subject.memberKeys ?? subject.sessions.map(sessionKey)) {
      riskRepresented.add(memberKey);
    }
  }
  const closeSubjects = new Map<string, Subject>();
  const attachedStopKeys = new Set<string>();
  for (const [sourceIndex, session] of sessions.entries()) {
    const key = sessionKey(session);
    const signal = stopSignal(session, sourceIndex);
    if (!signal || attachedStopKeys.has(key)) continue;
    const winning = subjects.get(key) ?? riskSubjects.get(key);
    if (winning) {
      winning.signals.push(signal);
      attachedStopKeys.add(key);
      continue;
    }
    if (riskRepresented.has(key) || closeSubjects.has(key)) continue;
    closeSubjects.set(key, {
      key,
      stableId: key,
      kind: 'session',
      section: 'close',
      primaryKind: signal.kind,
      signals: [signal],
      session,
      sessions: [session],
      asks: [],
      sourceIndex,
    });
    attachedStopKeys.add(key);
  }

  const comparator: Comparator = { generated, harnessOrder };
  const sorted = (map: Map<string, Subject>): Subject[] =>
    [...map.values()].sort((left, right) => compareSubjects(left, right, comparator));
  const needs = sorted(subjects);
  const risk = sorted(riskSubjects);
  const close = sorted(closeSubjects);
  const represented = new Set(needs.flatMap((subject) => subject.sessions.map(sessionKey)));
  for (const subject of risk) {
    if (subject.kind === 'collision') continue;
    for (const memberKey of subject.memberKeys ?? subject.sessions.map(sessionKey)) {
      represented.add(memberKey);
    }
  }
  for (const subject of close) {
    for (const session of subject.sessions) represented.add(sessionKey(session));
  }
  const nextSubjects = new Map<string, Subject>();
  const attachedTaskKeys = new Set<string>();
  for (const [sourceIndex, session] of sessions.entries()) {
    const key = sessionKey(session);
    const checkpoint = publishedTask(session);
    if (!checkpoint || attachedTaskKeys.has(key)) continue;
    const winning = subjects.get(key) ?? riskSubjects.get(key) ?? closeSubjects.get(key);
    if (winning) {
      winning.signals.push({
        kind: 'task',
        section: 'next',
        detail: { task: checkpoint, session },
        sourceIndex,
      });
      if (!winning.checkpoint) winning.checkpoint = checkpoint;
      attachedTaskKeys.add(key);
      continue;
    }
    if (represented.has(key) || nextSubjects.has(key)) continue;
    nextSubjects.set(key, {
      key,
      stableId: key,
      kind: 'session',
      section: 'next',
      primaryKind: 'task',
      signals: [
        { kind: 'task', section: 'next', detail: { task: checkpoint, session }, sourceIndex },
      ],
      session,
      sessions: [session],
      asks: [],
      sourceIndex,
      checkpoint,
    });
    attachedTaskKeys.add(key);
  }
  const next = sorted(nextSubjects);
  for (const subject of next) {
    for (const session of subject.sessions) represented.add(sessionKey(session));
  }
  const healthyByKey = new Map<string, Row>();
  for (const session of sessions) {
    const key = sessionKey(session);
    if (!represented.has(key) && !healthyByKey.has(key)) healthyByKey.set(key, session);
  }
  const healthySessions = [...healthyByKey.values()];
  const moving = healthySessions.filter((session) => session['state'] === 'working').length;
  const quiet = healthySessions.filter((session) => session['state'] === 'idle').length;
  // Read completeness qualifies the remainder; it does not invalidate a state derived from another
  // source.
  const partial = healthySessions.filter((session) => gapNames(session).length).length;
  return {
    needs,
    risk,
    close,
    next,
    healthy: {
      sessions: healthySessions,
      moving,
      quiet,
      unknown: healthySessions.length - moving - quiet,
      partial,
    },
    coverage: coverageOf(payload),
    counts: {
      needs: needs.length,
      risk: risk.length,
      close: close.length,
      next: next.length,
      moving,
      quiet,
      unknown: healthySessions.length - moving - quiet,
    },
    harnessOrder,
    representedSessionKeys: [...represented],
    generated,
    windowHours: nextNumber(payload['window_hours']),
    sessionCount: sessions.length,
  };
}

/* What a count change reads as to a screen reader, or nothing when no queue changed length. The first
   board has no predecessor, so it announces nothing: arriving is not a change. */
export function attentionAnnouncement(
  previous: AttentionModel | null,
  current: AttentionModel | null,
): string {
  if (!previous || !current) return '';
  const keys = ['needs', 'risk', 'close', 'next'] as const;
  if (keys.every((key) => previous.counts[key] === current.counts[key])) return '';
  const { counts } = current;
  const parts: string[] = [];
  if (counts.needs) parts.push(`${String(counts.needs)} need you`);
  if (counts.risk) parts.push(`${String(counts.risk)} at risk`);
  if (counts.close) parts.push(`${String(counts.close)} close the loop`);
  if (counts.next) parts.push(`${String(counts.next)} coming next`);
  if (!parts.length) parts.push('0 need you', '0 at risk');
  return `Attention updated: ${parts.join(', ')}`;
}
