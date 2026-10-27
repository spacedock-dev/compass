import { nextNumber } from '../api/bootstrap';
import { isRecord, type Row } from '../observed';
import {
  GOAL_VERDICT_LABEL,
  GOAL_VERDICT_LINES,
  GOAL_VERDICT_QUOTED_WHY,
  GOAL_VERDICT_WHY,
  GOAL_VERDICT_WHY_GOAL,
  goalVerdictClaim,
  goalVerdictPullRequest,
  goalVerdictQuoted,
  goalVerdictRemoval,
} from './sentences';
import type { WorkEntry } from '../intent/work';
import type { Shape } from './shape';

/* The harness's "goal met" verdict, as the row publishes it under `session_goal.verdict`, and what the card says
   of it. The verdict is the harness's claim (Claude Code's evaluator, or the Codex agent's own): this reads it,
   never believes it, and nothing here reaches a level
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

export interface HarnessGaveUp {
  readonly at: number;
  readonly reason: string;
}

/* The harness giving up on the goal, as the row publishes it under `session_goal_gave_up`, outside the goal
   because the harness ended it. Never a verdict: nothing that reads `met` reads this. A give-up with no moment
   is not shown, as a verdict with none is not. */
export function harnessGaveUp(session: Row | null | undefined): HarnessGaveUp | null {
  const gave = session?.['session_goal_gave_up'];
  if (!isRecord(gave)) return null;
  const at = nextNumber(gave['at']);
  if (at === null || at <= 0) return null;
  const reason = typeof gave['reason'] === 'string' ? gave['reason'].trim() : '';
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
  readonly clock: string;
  /** The time a removal dispute names, drawn as the card draws times; empty where the test names none. */
  readonly changedClock?: string;
  /** The entries the test cited, by fact id, so a confirmed pull request can be named. */
  readonly cited?: ReadonlyMap<string, WorkEntry>;
  /** The numbers the card gives entries, so a check the quoted text was found in can be named by its number. */
  readonly numbers?: ReadonlyMap<string, string>;
  /** The row's harness, which the claim names. */
  readonly harness?: string;
}): VerdictNote {
  const { verdict, shape } = input;
  const test = shape && !shape.malformed ? shape.goalVerdict : null;
  const state: VerdictState = !input.analyzed
    ? 'claim-only'
    : test && test.at === verdict.at
      ? (test.check as VerdictState)
      : 'unchecked';
  const tested = test && test.at === verdict.at ? test : null;
  const pr =
    tested?.why === 'pr-created-before'
      ? tested.cites.map((id) => input.cited?.get(id)).find((entry) => entry?.subject === 'pr')
      : undefined;
  const quotedIn =
    tested?.why === GOAL_VERDICT_QUOTED_WHY
      ? tested.cites.flatMap((id) => {
          const n = input.numbers?.get(id);
          return n ? [n] : [];
        })
      : [];
  // A claim with no reason was tested against the goal's words, so the sentence names the goal.
  const byGoal = verdict.reason === '';
  const why = tested
    ? tested.path && input.changedClock
      ? goalVerdictRemoval(tested.why, tested.path, input.changedClock)
      : quotedIn.length
        ? goalVerdictQuoted(quotedIn)
        : pr?.summary
          ? goalVerdictPullRequest(pr.summary, byGoal)
          : ((byGoal ? GOAL_VERDICT_WHY_GOAL : GOAL_VERDICT_WHY)[tested.why] ?? '')
    : '';
  const line = GOAL_VERDICT_LINES[state];
  return {
    state,
    label: GOAL_VERDICT_LABEL,
    claim: goalVerdictClaim(input.clock, input.harness),
    line: line ? line(why) : '',
    reason: verdict.reason,
  };
}
