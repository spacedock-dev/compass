import { compatSessKey } from '../api/identity';

/* Exact spellings of the persisted browser preferences and transport state. */
export const STORAGE_KEYS = {
  updateDismissed: 'compass.update-dismissed.v1',
  memoPrefix: 'compass.cockpit.memo.v2:',
  graphMode: 'compass.next.graph.mode',
  guardrailPrefix: 'compass.next.guardrails.',
  leader: 'compass.next.leader',
  revision: 'compass.next.revision',
  usageConsent: 'compass.next.usage.consent',
  workstreamCollapsed: 'compass.next.workstream.collapsed',
  observerConsent: 'compass.observer-model-consent.v1',
  cockpitProject: 'compass.projectCockpitProject',
  goalPrefix: 'compass.projectGoal.v1:',
  usage: 'compass.projectUsage.v1',
} as const;

/**
 * Exact harness and session id. `session` is the display id some rows carry instead of a sid; it
 * only ever completes a storage key, as in the legacy page, and is never an action identity.
 */
export interface SessionIdentity {
  readonly harness: string;
  readonly sid: string;
  readonly session?: string;
}

/** One implementation of the page's `sessKey`, shared with the API layer so the two cannot diverge. */
export const sessionKey: (session: SessionIdentity) => string = compatSessKey;
