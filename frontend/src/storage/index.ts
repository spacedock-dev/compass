/*
 * The one place the React client touches browser storage. Each family keeps the released key,
 * encoding, bounds and in-tab fallback of the legacy page, which stays readable in both
 * directions until its rollback is retired. Conformance: frontend/e2e/storage-conformance.mjs.
 */
import { browserBackend, storageAccess, type BackendProvider } from './backend';
import { createConsentStore, type ConsentStore } from './consent';
import { createCockpitProjectStore, createWorkstreamStore } from './flags';
import type { CockpitProjectStore, WorkstreamStore } from './flags';
import { createGoalStore, type GoalStore } from './goal';
import { createGraphModeStore, type GraphModeStore } from './graphMode';
import { createGuardrailStore, type GuardrailStore } from './guardrails';
import { STORAGE_KEYS } from './keys';
import { createLeaseStore, type LeaseStore } from './lease';
import { createMemoStore, type MemoStore } from './memo';
import { createRevisionStore, type RevisionStore } from './revision';
import { createUsageStore, type UsageStore } from './usage';

export type { Attempt, BackendProvider, StorageAccess, StorageBackend } from './backend';
export { browserBackend, storageAccess } from './backend';
export type { ConsentAnswer, ConsentStore } from './consent';
export type { CockpitProjectStore, WorkstreamStore } from './flags';
export type { GoalClear, GoalSave, GoalStore } from './goal';
export { GOAL_EDITOR_MAX_UTF16, goalKey } from './goal';
export type { GraphMode, GraphModeStore } from './graphMode';
export { decodeGraphModes, GRAPH_MODES, graphModeScope } from './graphMode';
export type { GuardrailChange, GuardrailRule, GuardrailStore } from './guardrails';
export {
  decodeGuardrails,
  GUARDRAIL_LIMIT,
  GUARDRAIL_TEXT_LIMIT,
  guardrailKey,
  normalizeGuardrail,
} from './guardrails';
export type { SessionIdentity } from './keys';
export { STORAGE_KEYS, sessionKey } from './keys';
export type { ElectionDecision, Lease, LeaseStore } from './lease';
export {
  createTabId,
  electionDecision,
  LEASE_RENEW_MS,
  LEASE_STALE_MS,
  leaseIsLive,
  parseLease,
} from './lease';
export type { MemoKind, MemoState, MemoStore } from './memo';
export { boundMemo, MEMO_LIMIT, memoKey } from './memo';
export type { RevisionStore } from './revision';
export { revisionFromStorageEvent, revisionNewer } from './revision';
export type { UsageCounts, UsageStore } from './usage';
export { decodeUsage, USAGE_COUNT_MAX, USAGE_LOAD_LIMIT } from './usage';

export interface LegacyStorage {
  readonly memo: MemoStore;
  readonly graphMode: GraphModeStore;
  readonly guardrails: GuardrailStore;
  readonly lease: LeaseStore;
  readonly revision: RevisionStore;
  readonly usageConsent: ConsentStore;
  readonly workstream: WorkstreamStore;
  readonly observerConsent: ConsentStore;
  readonly cockpitProject: CockpitProjectStore;
  readonly goal: GoalStore;
  readonly usage: UsageStore;
}

/**
 * Each instance owns the in-tab fallbacks the legacy page holds as module globals, so a store
 * created per document behaves like one page load. The provider is consulted on every access.
 */
export function createLegacyStorage(provider: BackendProvider = browserBackend): LegacyStorage {
  const access = storageAccess(provider);
  return {
    memo: createMemoStore(access),
    graphMode: createGraphModeStore(access),
    guardrails: createGuardrailStore(access),
    lease: createLeaseStore(access),
    revision: createRevisionStore(access),
    usageConsent: createConsentStore(access, STORAGE_KEYS.usageConsent),
    workstream: createWorkstreamStore(access),
    observerConsent: createConsentStore(access, STORAGE_KEYS.observerConsent),
    cockpitProject: createCockpitProjectStore(access),
    goal: createGoalStore(access),
    usage: createUsageStore(access),
  };
}
