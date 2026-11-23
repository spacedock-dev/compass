import { overlaid } from '../drift/overlay';
import { readingsOff, readingsOn } from '../drift/route';
import { driftCtxFor, useDriftVersion } from '../drift/state';
import { isRecord, type Row } from '../observed';
import { useDisplayed, useShell } from '../shell/context';

export function modelPause(payload: Row): boolean | null {
  if (readingsOff(payload)) return true;
  if (readingsOn(payload)) return false;

  // Summaries publishes the master pause reason even when annotations are off.
  const summary = payload['summaries'];
  if (!isRecord(summary)) return null;
  if (summary['reason'] === 'model-calls-paused') return true;
  if (summary['reason'] === 'summaries-off' || summary['reason'] === 'daily-cap') return false;
  return summary['consent'] === true ? false : null;
}

export function useAiPause() {
  const shell = useShell();
  const ctx = driftCtxFor(shell);
  useDriftVersion(ctx.drift);
  const board = useDisplayed((snapshot) => snapshot);
  const payload = board.data
    ? overlaid(board.data as unknown as Row, ctx.drift.getOverlay(), board.acceptedCount)
    : null;
  const fresh =
    !board.failures ||
    Boolean(ctx.drift.getOverlay().reading && ctx.drift.getOverlay().stamp === board.acceptedCount);
  const paused = payload && fresh ? modelPause(payload) : null;
  const pending = board.pending.some(
    (key) => key === 'reading-on' || key === 'reading-off' || /^reading-(off|on):/.test(key),
  );
  return { ctx, paused, fresh, pending };
}
