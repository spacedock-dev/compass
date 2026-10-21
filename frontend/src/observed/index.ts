/* The observed model: what the board says about its sessions, as facts that each know whether they were
   measured. The legacy page's `next-observed.js`, ported and held to it by the differential test. Views
   read it; nothing here fetches, reads the clock or touches the DOM. */
export {
  observeCapacity,
  type BoardRisk,
  type CapacitySublimit,
  type CapacityWindow,
} from './capacity';
export {
  delegatedWork,
  goalOf,
  landingOf,
  readHint,
  READING_TURN_STOP_HARNESSES,
  sessionDot,
  sessionStop,
  type DelegatedWork,
  type EndKind,
  type Goal,
  type Landing,
  type SessionDot,
  type SessionStop,
} from './landing';
export {
  observe,
  type Coverage,
  type Observed,
  type ObservedCounter,
  type ObservedTotals,
} from './model';
export { type ObservedProject } from './project';
export { labelOf, observeSession, pageTitleOf, type ObservedSession } from './session';
export { selectObserved } from './select';
export {
  ageSeconds,
  clock,
  durationSince,
  endedAt,
  exactAskOwner,
  gapNames,
  isRecord,
  isScanOnly,
  pair,
  payloadAskRows,
  payloadSessionRows,
  promptCopied,
  records,
  sessionKey,
  trimmed,
  type Pair,
  type Row,
} from './values';
