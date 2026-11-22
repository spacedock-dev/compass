import type { BoardSnapshot } from '../store/board';
import { observedFor } from '../observed/select';
import { sessionKey, sessionState, sessionStop, type ObservedSession } from '../observed';
import { asPayload, payloadSessionRows, type Row } from '../observed/values';
import { stopRecord } from '../observed/landing';
import { measuredLocation } from '../observed/location';
import { attentionModel, type AttentionModel, type Signal, type Subject } from './model';
import { kindLabel } from './text';

const byBody = new WeakMap<object, AttentionModel>();

/* The model of the accepted body, computed once per body: a subscriber that selects it gets the same
   object back until the data is replaced, which `useSyncExternalStore` needs, and a poll that changed
   nothing costs nothing. Null before the first board, so "nothing has arrived" is never read as an empty
   queue. */
export function attentionFor(body: object | null): AttentionModel | null {
  if (!body) return null;
  let cached = byBody.get(body);
  if (!cached) {
    cached = attentionModel(body);
    byBody.set(body, cached);
  }
  return cached;
}

export function selectAttention(snapshot: BoardSnapshot): AttentionModel | null {
  return attentionFor(snapshot.data);
}

export interface AttentionSelection {
  readonly waitingOnYou: readonly ObservedSession[];
  readonly worthALook: ReadonlyMap<ObservedSession, string>;
  readonly worthALookNotices: readonly Subject[];
  readonly readyToWrapUp: readonly ObservedSession[];
  readonly working: readonly ObservedSession[];
  readonly quiet: readonly ObservedSession[];
  readonly ended: readonly ObservedSession[];
  readonly offCountRisks: readonly Subject[];
  /** A published collection can have independently measured notices even if every session read fails. */
  readonly counts: {
    readonly waitingOnYou: number;
    readonly worthALook: number;
    readonly readyToWrapUp: number;
    readonly working: number;
    readonly badge: number;
  } | null;
}

const selectionByBody = new WeakMap<object, AttentionSelection>();

function dirtyEndReason(source: Row): string {
  const changed = source['changed'];
  const reason = 'Ended with uncommitted work';
  if (typeof changed !== 'number' || !Number.isInteger(changed) || changed < 0) return reason;
  return `${reason} (${String(changed)} changed ${changed === 1 ? 'entry' : 'entries'})`;
}

function sessionRiskReason(signal: Signal, source: Row, ended: boolean): string | undefined {
  switch (signal.kind) {
    case 'loop':
    case 'quiet-launch':
      return kindLabel(signal.kind);
    case 'long-turn':
      return ended ? undefined : kindLabel(signal.kind);
    case 'attribution': {
      if (ended) return undefined;
      const stop = sessionStop(source);
      if (stop?.kind === 'hook')
        return 'A stop was recorded while the session still reported activity';
      if (stop?.kind === 'transcript')
        return `Git state was reported without a stop hook. A turn stop appears in ${stopRecord(source)}`;
      return 'Git state was reported without a recorded stop';
    }
  }
}

function buildSelection(body: object, payload: Row, model: AttentionModel): AttentionSelection {
  const observed = observedFor(body);
  const sources = payloadSessionRows(payload);
  const sourceByRow = new Map(observed.sessions.map((row, index) => [row, sources[index]]));
  const byIdentity = new Map<string, ObservedSession[]>();
  for (const row of [...observed.active, ...observed.history]) {
    const key = sessionKey(row);
    const copies = byIdentity.get(key);
    if (copies) copies.push(row);
    else byIdentity.set(key, [row]);
  }
  const sessionReasons = new Map<ObservedSession, string>();
  // The legacy queue can move a signal onto a waiting subject. Its source index still names the row
  // that carried the evidence. Use that occurrence before applying this selector's waiting rule.
  for (const subject of [...model.risk, ...model.needs]) {
    if (subject.kind !== 'session') continue;
    const ended = byIdentity.get(subject.key)?.some((row) => row.isEnded) ?? false;
    for (const signal of subject.signals) {
      const row = observed.sessions[signal.sourceIndex];
      const source = sources[signal.sourceIndex];
      if (!row || !source || sessionReasons.has(row)) continue;
      const reason = sessionRiskReason(signal, source, ended);
      if (reason) sessionReasons.set(row, reason);
    }
  }

  const sharedLabelMembers = new Set<Row>();
  const worthALookNotices: Subject[] = [];
  const offCountRisks =
    payload['ask'] === true ? model.needs.filter((subject) => !subject.session) : [];
  for (const subject of model.risk) {
    if (subject.kind === 'quota') {
      // Quota windows have harness/scope evidence and no exact session owner.
      worthALookNotices.push(subject);
      continue;
    }
    if (subject.primaryKind === 'checkout') {
      offCountRisks.push(subject);
      continue;
    }
    if (subject.primaryKind === 'collision') {
      const members = subject.sessions.filter(measuredLocation);
      const locations = members.map(measuredLocation);
      if (new Set(locations).size < 2) {
        offCountRisks.push(subject);
        continue;
      }
      for (const member of members) sharedLabelMembers.add(member);
    }
  }

  const waitingOnYou: ObservedSession[] = [];
  const worthALook = new Map<ObservedSession, string>();
  const readyToWrapUp: ObservedSession[] = [];
  const working: ObservedSession[] = [];
  const quiet: ObservedSession[] = [];
  const ended: ObservedSession[] = [];
  for (const copies of byIdentity.values()) {
    const wait = copies.find((row) => row.isNeeds || row.askKnown);
    if (wait) {
      waitingOnYou.push(wait);
      continue;
    }
    const row = copies[0];
    if (!row) continue;
    const state = sessionState(row);
    if (state === 'Working') working.push(row);
    if (state === 'Quiet') quiet.push(row);
    if (state === 'Ended') ended.push(row);

    const dirty = copies.find((row) => row.isEnded && sourceByRow.get(row)?.['dirty'] === true);
    const dirtySource = dirty && sourceByRow.get(dirty);
    if (dirty && dirtySource) {
      worthALook.set(dirty, dirtyEndReason(dirtySource));
      continue;
    }
    const risky = copies.find((row) => sessionReasons.has(row));
    const reason = risky && sessionReasons.get(risky);
    if (risky && reason) {
      worthALook.set(risky, reason);
      continue;
    }
    const shared = copies.find((row) => {
      const source = sourceByRow.get(row);
      return source && sharedLabelMembers.has(source);
    });
    if (shared) {
      worthALook.set(shared, 'Shared project label');
      continue;
    }
    const clean = copies.find((row) => row.isEnded && sourceByRow.get(row)?.['dirty'] === false);
    if (clean) readyToWrapUp.push(clean);
  }
  const { discovered, failed } = model.coverage.gates;
  const unavailable = model.sessionCount === 0 && failed > 0 && failed === discovered;
  return {
    waitingOnYou,
    worthALook,
    worthALookNotices,
    readyToWrapUp,
    working,
    quiet,
    ended,
    offCountRisks,
    counts: unavailable
      ? null
      : {
          waitingOnYou: waitingOnYou.length,
          worthALook: worthALook.size,
          readyToWrapUp: readyToWrapUp.length,
          working: working.length,
          badge: waitingOnYou.length + worthALook.size,
        },
  };
}

export function attentionSelectionFor(body: object | null): AttentionSelection | null {
  if (!body) return null;
  const cached = selectionByBody.get(body);
  if (cached) return cached;
  const payload = asPayload(body);
  if (!Array.isArray(payload['sessions'])) return null;
  const model = attentionFor(body);
  if (!model) return null;
  const selection = buildSelection(body, payload, model);
  selectionByBody.set(body, selection);
  return selection;
}

export function selectAttentionSelection(snapshot: BoardSnapshot): AttentionSelection | null {
  return attentionSelectionFor(snapshot.data);
}
