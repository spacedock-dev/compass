import { nextNumber } from '../api/bootstrap';
import { durationSince, isRecord, promptCopied, type Row } from '../observed';
import type { RouteInput } from '../router/grammar';
import { formatDuration } from '../shell/format';
import {
  type AttentionModel,
  type Signal,
  type Subject,
  subjectAge,
  subjectIdentity,
} from './model';

/* The sentences an Attention subject is read through: why it is here, whose outcome it serves, what it
   observes now, what is next and where the claim came from. The legacy page's `nextAttention*` text
   builders, ported with the model and held to them by the same differential. Each returns what the board
   published and a word for what it did not, and none of them reads a clock: an age is the payload's own
   `generated` against a published stamp, so a subject ages only when a new board arrives. */

export const KIND_LABELS = new Map<string, string>([
  ['ask', 'Question waiting'],
  ['input', 'Input signal observed'],
  ['attribution', 'Attribution conflict'],
  ['loop', 'Repeated tool failures'],
  ['quota', 'Quota pressure'],
  ['long-turn', 'Long-running turn'],
  ['collision', 'Label shared across locations'],
  ['checkout', 'Concurrent sessions in one checkout'],
  ['quiet-launch', 'Quiet delegated launch'],
  ['stop-dirty', 'Stop observed with uncommitted work'],
  ['stop-clean', 'Stop observed; git state clean'],
  ['stop-unknown', 'Stop observed; git state not measured'],
  ['end-dirty', 'Session ended with uncommitted work'],
  ['end-clean', 'Session ended; git state clean'],
  ['end-unknown', 'Session ended; git state not measured'],
  ['task', 'Published task'],
]);

const FALLBACK_KIND = 'Source signal observed';

export function kindLabel(kind: string): string {
  return KIND_LABELS.get(kind) ?? FALLBACK_KIND;
}

const text = (value: unknown): string => String(value == null ? '' : value);

export function harnessLabel(model: AttentionModel, harness: unknown): string {
  const key = text(harness);
  const row = model.coverage.gates.rows.find((item) => String((item as Row)['key'] || '') === key);
  const label = text(row && row['label'] != null ? row['label'] : '').trim();
  return label || key || 'Source not identified';
}

function askedAssignment(session: Row | null): string {
  const instruction = session?.['instruction'];
  if (
    !isRecord(instruction) ||
    instruction['label'] !== 'asked' ||
    typeof instruction['text'] !== 'string' ||
    promptCopied(session, 'instruction')
  ) {
    return '';
  }
  return instruction['text'].trim();
}

/* The workflow's goal, but only when every workflow the session reports agrees on one. Two goals is not
   a goal. */
function workflowGoal(session: Row | null): string {
  const spacedock = session?.['spacedock'];
  const workflows =
    isRecord(spacedock) && Array.isArray(spacedock['workflows'])
      ? (spacedock['workflows'] as unknown[])
      : [];
  const goals: string[] = [];
  for (const workflow of workflows) {
    const goal =
      isRecord(workflow) && typeof workflow['goal'] === 'string' ? workflow['goal'].trim() : '';
    if (goal && !goals.includes(goal)) goals.push(goal);
  }
  return goals.length === 1 ? (goals[0] as string) : '';
}

export function identityText(
  subject: Subject | { readonly session: Row | null },
  model: AttentionModel,
): string {
  if ('kind' in subject && subject.kind === 'quota') {
    const identity = subjectIdentity(subject);
    return `${harnessLabel(model, identity?.['harness'])} · ${String((identity && identity['project']) || 'Quota window')}`;
  }
  if ('kind' in subject && subject.kind === 'collision') {
    const detail = subject.signals[0]?.detail ?? {};
    return `${detail.label ? `${detail.label} display label` : 'Across display labels'} · ${String(Number(detail.memberCount) || 0)} exact sessions`;
  }
  const identity = subjectIdentity(subject);
  if (identity) {
    const project = text(identity['project']) || 'Unlabelled display';
    const harness = harnessLabel(model, identity['harness']);
    const sid = text(identity['sid']) || 'identity not reported';
    return `${project} · ${harness} · ${sid}`;
  }
  const ask = 'asks' in subject && Array.isArray(subject.asks) ? (subject.asks[0] ?? null) : null;
  const project = text(ask?.['project']) || 'Unlabelled display';
  const harness = harnessLabel(model, ask?.['harness']);
  const sid = text(ask?.['session_id']) || 'identity not reported';
  return `${project} · ${harness} · ${sid}`;
}

export interface Outcome {
  readonly label: 'OUTCOME' | 'IDENTITY';
  readonly text: string;
}

/* The reader's own assignment when the session was asked one, else the one goal its workflows agree on,
   else only who the subject is: an outcome is never composed. */
export function subjectOutcome(subject: Subject, model: AttentionModel): Outcome {
  const assignment = askedAssignment(subject.session);
  if (assignment) return { label: 'OUTCOME', text: assignment };
  const goal = workflowGoal(subject.session);
  if (goal) return { label: 'OUTCOME', text: goal };
  return { label: 'IDENTITY', text: identityText(subject, model) };
}

function attributionNow(detail: Signal['detail']): string {
  if (detail.ask && detail.owner) {
    const askProject = text(detail.ask['project']);
    const ownerProject = text(detail.owner['project']);
    return `Sources disagree · request display label: ${askProject} · session display label: ${ownerProject}`;
  }
  const readings: string[] = [];
  if (detail.state) readings.push(`state: ${detail.state}`);
  if (detail.active === true) readings.push('active: true');
  if (detail.finishedAt != null) readings.push(`stop observed: ${String(detail.finishedAt)}`);
  if (detail.dirty != null) readings.push(`dirty: ${String(detail.dirty)}`);
  if (detail.changed != null) readings.push(`changed entries: ${String(detail.changed)}`);
  return readings.length ? `Sources disagree · ${readings.join(' · ')}` : 'Sources disagree';
}

/* Shared by the stop and end kinds because the git half of the sentence is the same reading either way;
   only what happened to the session differs. */
function closeText(kind: string, detail: Signal['detail']): string {
  if (kind.endsWith('-dirty')) {
    return Number.isInteger(detail.changedEntries)
      ? `${String(detail.changedEntries)} changed entries`
      : 'Uncommitted work observed';
  }
  if (kind.endsWith('-clean')) return 'Git state reported clean';
  return 'Git state was not measured';
}

export interface NowRow {
  readonly text: string;
  readonly note: string;
}

function signalNow(signal: Signal, subject: Subject, model: AttentionModel): NowRow {
  const detail = signal.detail;
  if (signal.kind === 'ask') {
    const ask = detail.ask;
    const question = text(ask?.['question']).trim();
    const choices = ask?.['options'];
    const options = Array.isArray(choices) ? choices.length : 0;
    return { text: question, note: options ? `${String(options)} published options` : '' };
  }
  if (signal.kind === 'input') {
    const session = subject.session;
    const detailText = text((session && session['state_detail']) || '').trim();
    const sentence = detailText || 'Needs-input state reported';
    if (session?.['wait_unconfirmed']) {
      return {
        text: sentence,
        note: 'Unconfirmed: no positive observation in 5m; prompt may still be standing',
      };
    }
    return { text: sentence, note: '' };
  }
  if (signal.kind === 'attribution') return { text: attributionNow(detail), note: '' };
  if (signal.kind === 'loop') {
    const tool = text(detail.tool).trim();
    // The count said out loud is the turn total wherever it is bigger, because the peak run
    // understates a turn a success split in two.
    const count = detail.failures == null ? detail.errors : detail.failures;
    const what = tool ? `${tool} failed` : 'Tool failures reported';
    return {
      text:
        detail.barren === true
          ? `${what} ${String(count)} times, nothing succeeded`
          : `${what} ${String(count)} times`,
      note: '',
    };
  }
  if (signal.kind === 'quota') {
    /* The pace is stated beside the level whenever it was measured, because the level alone cannot say
       why a row at 34% is here and a row at 88% is not. */
    const pace = nextNumber(detail.paceRatio);
    return {
      text:
        pace === null
          ? `${String(detail.pct)}% reported`
          : `${String(detail.pct)}% reported, ${pace.toFixed(1)}× the pace this window sustains`,
      note: '',
    };
  }
  if (signal.kind === 'long-turn') {
    const session = subject.session ?? detail.session ?? {};
    const state = text(session['state_detail'] || 'Working').trim() || 'Working';
    const turn = session['turn'];
    const elapsed =
      isRecord(turn) && typeof turn['elapsed_h'] === 'string' ? turn['elapsed_h'].trim() : '';
    return { text: elapsed ? `${state} · ${elapsed} elapsed` : state, note: '' };
  }
  if (signal.kind === 'quiet-launch') {
    return { text: text(detail.text), note: 'Recorded activity only; not a process check.' };
  }
  if (signal.kind === 'collision' || signal.kind === 'checkout') {
    return {
      text: text(detail.text),
      note: 'Compare title, worktree, id and start time',
    };
  }
  if (signal.kind.startsWith('stop-')) return { text: closeText(signal.kind, detail), note: '' };
  if (signal.kind.startsWith('end-')) {
    /* The age of the END and never of the stop: they are different moments, and an ended row usually
       carries no stop at all. */
    const since = durationSince(model.generated, detail.endedAt);
    const sentence = closeText(signal.kind, detail);
    return {
      text: since ? `${sentence} · ended ${since} ago` : sentence,
      note: 'This session id reported its own end',
    };
  }
  if (signal.kind === 'task') {
    return {
      text: subject.checkpoint?.status === 'in_progress' ? 'In progress' : 'Pending',
      note: '',
    };
  }
  return { text: 'Source signal observed', note: '' };
}

/* A task may stay attached to a stronger signal on its own session. Location warnings never own it. */
function signalAttribution(signal: Signal, model: AttentionModel): string {
  const session = signal.detail.session;
  return session ? identityText({ session }, model) : '';
}

export function subjectNow(subject: Subject, model: AttentionModel): NowRow[] {
  const rows: NowRow[] = [];
  for (const [index, signal] of subject.signals.entries()) {
    if (signal.kind === 'task' && subject.primaryKind !== 'task') continue;
    const row = signalNow(signal, subject, model);
    if (!row.text) continue;
    const secondary = index > 0;
    const label = kindLabel(signal.kind);
    const attribution = signalAttribution(signal, model);
    const prefix = [attribution, secondary ? label : ''].filter(Boolean).join(' · ');
    rows.push({ ...row, text: prefix ? `${prefix}: ${row.text}` : row.text });
  }
  return rows;
}

function checkpointText(subject: Subject): string {
  const checkpoint = subject.checkpoint;
  if (!checkpoint) return '';
  const task = text(checkpoint.activeForm || checkpoint.subject).trim();
  if (task) return task;
  if (typeof checkpoint.resetAt === 'number' && Number.isFinite(checkpoint.resetAt)) {
    const instant = new Date(checkpoint.resetAt * 1000);
    return Number.isNaN(instant.getTime()) ? '' : `Reset at ${instant.toISOString()}`;
  }
  return '';
}

export function checkpointRows(subject: Subject, model: AttentionModel): string[] {
  const rows: string[] = [];
  for (const signal of subject.signals) {
    if (signal.kind !== 'task') continue;
    const task = signal.detail.task;
    const label = text(task && (task['activeForm'] || task['subject'])).trim();
    if (!label) continue;
    const attribution = signalAttribution(signal, model);
    rows.push(attribution ? `${attribution}: ${label}` : label);
  }
  if (rows.length) return rows;
  const checkpoint = checkpointText(subject);
  return checkpoint ? [checkpoint] : [];
}

export function subjectSource(subject: Subject, model: AttentionModel): string {
  const identity = subjectIdentity(subject);
  const ask = subject.asks[0] ?? null;
  const harness = (identity && identity['harness']) || (ask && ask['harness']) || '';
  const parts: string[] = [];
  if (subject.responsibility) parts.push(subject.responsibility);
  parts.push(harnessLabel(model, harness));
  const age = subjectAge(subject, model.generated);
  if (age !== null) parts.push(formatDuration(age) as string);
  return parts.join(' · ');
}

/* The session a subject opens, or the Sessions list when the subject names none exactly. A display id is
   never a route: it needs a project and a sid. */
export function subjectRoute(subject: Subject): RouteInput {
  if (subject.kind === 'collision')
    return subject.identity?.project
      ? { view: 'project', project: subject.identity.project }
      : { view: 'sessions' };
  const identity = subjectIdentity(subject);
  const project = text(identity && identity['project']);
  const harness = text(identity && identity['harness']);
  const sid = text(identity && identity['sid']);
  return project && sid
    ? { view: 'session', project, harness, session: sid }
    : { view: 'sessions' };
}

export function subjectTitle(subject: Subject): {
  readonly title: string;
  readonly secondary: string;
} {
  const extra = subject.signals.length - 1;
  return {
    title: kindLabel(subject.primaryKind),
    secondary:
      extra > 0 ? ` · ${String(extra)} additional source signal${extra === 1 ? '' : 's'}` : '',
  };
}
