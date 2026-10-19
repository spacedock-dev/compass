import { use, useEffect } from 'react';
import {
  parseFocusedSummary,
  parseGrant,
  stampModel,
  type FocusedSummary,
  type StoredSummary,
  type SummaryGrant,
  type SummaryJob,
} from '../api/summary';
import type { SessionIdentity } from '../api/types';
import { useDrift } from '../drift/context';
import { TourContext } from '../sample/tourContext';
import { useShell } from '../shell/context';
import { autoStartDue, summaryStamp, type ReasonContext } from './summary';
import { startSummary } from './summaryActions';
import { grantShown, summaryHeldFor, useSummaryHeld, type SessionSummaryHeld } from './summaryHeld';

/* The summary card's state, read once per render from the board, the focused context and this tab's held
   answers, and the one post a finished session's open makes. */

export type Opener = (id: string, n: string | null) => void;

export interface SummaryState {
  readonly identity: SessionIdentity | null;
  readonly key: string;
  readonly harness: string;
  readonly harnessLabel: string;
  readonly running: boolean;
  /** The grant as drawn, or null where this server publishes no summaries. */
  readonly grant: SummaryGrant | null;
  readonly focused: FocusedSummary | null;
  readonly stored: StoredSummary | null;
  readonly job: SummaryJob | null;
  readonly held: SessionSummaryHeld;
  readonly reasons: ReasonContext;
  /** The open of this finished session is due to post its one summary start. */
  readonly due: boolean;
}

export function useSummaryState(
  context: { readonly data: unknown; readonly revision: number } | undefined,
  running: boolean,
  harnessLabel: string,
): SummaryState {
  const { model } = useDrift();
  const shell = useShell();
  const sample = use(TourContext);
  const store = summaryHeldFor(shell.runtime);
  const key = model.key;
  const held = useSummaryHeld(store, key);
  const grant = grantShown(store, parseGrant(model.payload['summaries']), model.generated);
  const focused = parseFocusedSummary(context?.data);
  /* The job a start answered stands until a context read after that answer says what the server holds. */
  const job =
    focused?.job ?? (held.job && (context?.revision ?? 0) <= held.jobAt ? held.job : null);
  const ended = typeof model.session['ended_at'] === 'number' && model.session['ended_at'] > 0;
  const due =
    !held.opened &&
    model.identity !== null &&
    autoStartDue({ grant, focused, harness: model.harness, ended, sample });
  return {
    due,
    identity: model.identity,
    key,
    harness: model.harness,
    harnessLabel,
    running,
    grant,
    focused,
    stored: focused?.summary ?? null,
    job,
    held,
    reasons: {
      grant,
      harness: harnessLabel,
      largest: held.refusal?.largest ?? null,
    },
  };
}

/* The one summary a finished session gets when it is opened, posted once per session per page load. */
export function useOpenSummary(state: SummaryState): void {
  const shell = useShell();
  const { due, identity } = state;
  useEffect(() => {
    if (due && identity) void startSummary(shell, identity, 'start', 'open');
  }, [due, identity, shell]);
}

export function summaryHeader(state: SummaryState): string {
  if (!state.stored) return '';
  return summaryStamp(state.stored, state.running, stampModel(state.stored.modelStamp));
}
