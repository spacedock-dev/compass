import { intentKey } from '../intent/derive';
import { useDisplayed } from '../shell/context';
import { useDrift } from './context';
import { readingBoard, type Board } from './flip';
import { promptReadingRefusal } from './route';

export interface RunBoard {
  readonly board: Board;
  /** The press's refusal as the card computed it, before the board's ranking. */
  readonly refusal: string;
}

/* The board's half of whether a press can run. The card's body and its header's re-run control both read it.
   Only the body counts a pass of the drawn card (`advance`): the flip ledger tells an entry it drew on the pass
   before from one it did not by that count, so a header that redrew on its own, twice, would have made the
   body's entry look undrawn and said nothing of a change that had held. The header reads at the epoch the body
   last drew. */
export function useRunBoard(advance = false): RunBoard {
  const { ctx, model } = useDrift();
  const { session, key } = model;
  const epoch = advance ? ctx.drift.nextEpoch() : ctx.drift.epoch();
  const saving = useDisplayed((snapshot) =>
    snapshot.pending.includes(`${intentKey(session)}:save`),
  );
  const request = ctx.intent.held.requests.get(key);
  const now = ctx.shell.clock.now();
  const input = { input: model.input, saving, answered: request, nowMs: now };
  const refusal = promptReadingRefusal(input);
  const heldLive = promptReadingRefusal(input, true);
  const board = readingBoard(ctx, {
    session,
    reason: refusal,
    heldLive,
    payload: model.base,
    epoch,
    request,
  });
  return { board, refusal };
}
