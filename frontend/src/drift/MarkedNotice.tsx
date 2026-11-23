import { nextNumber } from '../api/bootstrap';
import { ActionButton } from '../intent/ActionButton';
import { markNotAccurate } from './actions';
import { useDrift } from './context';
import { RESULT_MARK_UNSAVED, RESULT_MARKED, RESULT_UNMARK } from './sentences';

/* What stands where the level was once the reader has marked a reading inaccurate: the one message that says
   so, with the way back (Undo) and the way forward (Analyze again) beside it. It asks nothing it keeps nowhere:
   an optional "what was wrong" choice lived in this tab, was sent to no one and outlived the reading, so it was
   dropped rather than stored. The reading's verdicts stay below it, dimmed, so the message is the only place that says they were
   disowned. The Undo carries the focus key the mark's own press holds, so focus follows the press from the
   footer to here. */
export function MarkedNotice() {
  const { ctx, model } = useDrift();
  const readAt = nextNumber(model.raw?.['read_at']);
  const key = model.key;
  const unsaved = ctx.drift.notAccurate.has(key);
  return (
    <div className="flex flex-col gap-2" data-next-drift-marked>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
        <p className="next-session-drift-limit m-0" role="status">
          {RESULT_MARKED}
        </p>
        {readAt === null ? null : (
          <ActionButton
            weight="quiet"
            label={RESULT_UNMARK}
            busyLabel="Saving…"
            pendingKey={`not-accurate:${key}`}
            action="not-accurate"
            arg={String(readAt)}
            focusKey={`not-accurate:${key}`}
            onPress={() => {
              if (model.identity) void markNotAccurate(ctx, model.identity, readAt, true);
            }}
          />
        )}
      </div>
      {unsaved ? (
        <p className="next-cockpit-reading-why m-0" role="status">
          {RESULT_MARK_UNSAVED}
        </p>
      ) : null}
    </div>
  );
}
