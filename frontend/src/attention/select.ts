import type { BoardSnapshot } from '../store/board';
import { observedFor } from '../observed/select';
import { sessionKey, sessionState, type ObservedSession } from '../observed';
import { asPayload, endedAt, payloadSessionRows, type Row } from '../observed/values';
import { measuredLocation } from '../observed/location';
import { attentionModel, type AttentionModel, type Subject } from './model';
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
  readonly readyToWrapUp: readonly ObservedSession[];
  readonly working: readonly ObservedSession[];
  readonly offCountRisks: readonly Subject[];
  readonly counts: {
    readonly waitingOnYou: number;
    readonly worthALook: number;
    readonly readyToWrapUp: number;
    readonly working: number;
    readonly badge: number;
  };
}

const selectionByBody = new WeakMap<object, AttentionSelection>();

function dirtyEndReason(source: Row): string {
  const changed = source['changed'];
  const reason = 'Ended with uncommitted work';
  if (typeof changed !== 'number' || !Number.isInteger(changed) || changed < 0) return reason;
  return `${reason} (${String(changed)} changed ${changed === 1 ? 'entry' : 'entries'})`;
}

function buildSelection(body: object, payload: Row, model: AttentionModel): AttentionSelection {
  const observed = observedFor(body);
  const sources = payloadSessionRows(payload);
  const sourceByRow = new Map(observed.sessions.map((row, index) => [row, sources[index]]));
  const reasons = new Map<string, string>();
  const offCountRisks =
    payload['ask'] === true ? model.needs.filter((subject) => !subject.session) : [];
  for (const subject of model.risk) {
    if (subject.kind === 'session') {
      const ended = endedAt(subject.session) !== null;
      const signal = subject.signals.find(
        ({ kind, section }) => section === 'risk' && (!ended || kind !== 'attribution'),
      );
      if (!signal) continue;
      const reason =
        signal.kind !== 'attribution'
          ? kindLabel(signal.kind)
          : signal.detail.finishedAt
            ? 'A stop was recorded while the session still reported activity'
            : 'Git state was reported without a recorded stop';
      reasons.set(subject.key, reason);
      continue;
    }
    if (subject.primaryKind === 'collision') {
      const locations = subject.sessions.map(measuredLocation).filter(Boolean);
      if (new Set(locations).size < 2) {
        offCountRisks.push(subject);
        continue;
      }
      for (const member of subject.sessions.filter(measuredLocation)) {
        const key = sessionKey(member);
        if (!reasons.has(key)) reasons.set(key, 'Shared project label');
      }
    } else {
      // Quota windows have harness/scope evidence and no exact session owner.
      offCountRisks.push(subject);
    }
  }

  const rows = [...observed.active, ...observed.history];
  const waiting = new Map<string, ObservedSession>();
  for (const row of rows) {
    const key = sessionKey(row);
    if ((row.isNeeds || row.askKnown) && !waiting.has(key)) waiting.set(key, row);
  }
  const waitingOnYou = [...waiting.values()];
  const worthALook = new Map<ObservedSession, string>();
  const readyToWrapUp: ObservedSession[] = [];
  const working: ObservedSession[] = [];
  // Active copies render before history and can suppress a repeated history row.
  const counted = new Set(waiting.keys());
  for (const row of rows) {
    const key = sessionKey(row);
    if (counted.has(key)) continue;
    counted.add(key);
    const source = sourceByRow.get(row);
    if (sessionState(row) === 'Working') working.push(row);
    if (row.isEnded && source?.['dirty'] === false) {
      readyToWrapUp.push(row);
      continue;
    }
    if (row.isEnded && source?.['dirty'] === true) {
      worthALook.set(row, dirtyEndReason(source));
      continue;
    }
    const reason = reasons.get(key);
    if (reason) worthALook.set(row, reason);
  }
  return {
    waitingOnYou,
    worthALook,
    readyToWrapUp,
    working,
    offCountRisks,
    counts: {
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
