import { nextNumber } from '../api/bootstrap';
import { isRecord, type Row } from '../observed';
import {
  GOAL_VERDICT_LABEL,
  GOAL_VERDICT_LINES,
  GOAL_VERDICT_WHY,
  goalVerdictClaim,
} from './sentences';
import type { Shape } from './shape';

/* The harness's "goal met" verdict, as the row publishes it under `session_goal.verdict`, and what the card says
   of it. The verdict is Claude Code's claim: this reads it, never believes it, and nothing here reaches a level
   or a check. Compass's test of it is the reading's own `goal_verdict`, read through the shape contract. */

export interface HarnessVerdict {
  readonly at: number;
  readonly reason: string;
}

/* A `met: true` verdict with a time, from a row whose goal holds one. Anything else (no goal, a verdict that is
   not met, one with no moment, a non-mapping) is no verdict: a claim this page cannot place in time is not shown. */
export function harnessVerdict(session: Row | null | undefined): HarnessVerdict | null {
  const goal = session?.['session_goal'];
  if (!isRecord(goal)) return null;
  const verdict = goal['verdict'];
  if (!isRecord(verdict) || verdict['met'] !== true) return null;
  const at = nextNumber(verdict['at']);
  if (at === null || at <= 0) return null;
  const reason = typeof verdict['reason'] === 'string' ? verdict['reason'].trim() : '';
  return { at, reason };
}

export type VerdictState = 'claim-only' | 'unchecked' | 'agrees' | 'disputed' | 'unconfirmed';

export interface VerdictNote {
  readonly state: VerdictState;
  readonly label: string;
  /** "Claude Code marked this goal met at 16:44." */
  readonly claim: string;
  /** Compass's side, in Compass's voice. */
  readonly line: string;
  readonly reason: string;
}

/* The note for one verdict. No analysis at all is the claim alone. A reading that is unreadable, or made
   before this verdict, or that carries no test of it, has not checked it. Only a test of this very verdict
   (its time equal) can say agrees, disputed or unconfirmed. */
export function verdictNote(input: {
  readonly verdict: HarnessVerdict;
  readonly analyzed: boolean;
  readonly shape: Shape | null;
  readonly harness: string;
  readonly clock: string;
}): VerdictNote {
  const { verdict, shape } = input;
  const test = shape && !shape.malformed ? shape.goalVerdict : null;
  const state: VerdictState = !input.analyzed
    ? 'claim-only'
    : test && test.at === verdict.at
      ? (test.check as VerdictState)
      : 'unchecked';
  const why = test && test.at === verdict.at ? (GOAL_VERDICT_WHY[test.why] ?? '') : '';
  const line = GOAL_VERDICT_LINES[state];
  return {
    state,
    label: GOAL_VERDICT_LABEL,
    claim: goalVerdictClaim(input.harness, input.clock),
    line: line ? line(why) : '',
    reason: verdict.reason,
  };
}
