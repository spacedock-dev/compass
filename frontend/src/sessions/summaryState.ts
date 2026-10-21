import { use, useEffect } from 'react';
import {
  jobActive,
  parseFocusedSummary,
  parseGrant,
  stampModel,
  type FocusedSummary,
  type StoredSummary,
  type SummaryGrant,
  type SummaryJob,
  type SummaryPlan,
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
  readonly plan: SummaryPlan | null;
  readonly job: SummaryJob | null;
  readonly held: SessionSummaryHeld;
  readonly reasons: ReasonContext;
  /** This open's one decision is due now: the first render holding the board's grant and the focused answer. */
  readonly deciding: boolean;
  /** That decision posts the open's one summary start. */
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
  /* Decided once per session per page load, at the first render that can decide it, and not again: a session
     that ends while open, a cap that lifts, the grant returning, or a summary deleted in another tab is not
     summarized on this open ([answer 5](../../../docs/design-session-summary.md#the-ruling)). */
  const deciding = !held.opened && model.identity !== null && grant !== null && focused !== null;
  const due = deciding && autoStartDue({ grant, focused, harness: model.harness, ended, sample });
  return {
    deciding,
    due,
    identity: model.identity,
    key,
    harness: model.harness,
    harnessLabel,
    running,
    grant,
    focused,
    stored: focused?.summary ?? null,
    plan: focused?.plan ?? null,
    job,
    held,
    reasons: {
      grant,
      harness: harnessLabel,
      largest: held.refusal?.largest ?? null,
    },
  };
}

/* The one summary a finished session gets when it is opened, posted once per session per page load, and the
   decision not to post recorded the same way. */
export function useOpenSummary(state: SummaryState): void {
  const shell = useShell();
  const { deciding, due, identity, key } = state;
  useEffect(() => {
    if (!deciding || !identity) return;
    if (due) void startSummary(shell, identity, 'start', 'open');
    else summaryHeldFor(shell.runtime).patch(key, { opened: true });
  }, [deciding, due, identity, key, shell]);
}

export function summaryHeader(state: SummaryState): string {
  if (!state.stored) return '';
  return summaryStamp(
    state.stored,
    state.running,
    stampModel(state.stored.modelStamp),
    jobActive(state.job),
  );
}
