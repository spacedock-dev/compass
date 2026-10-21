import { nextNumber } from '../api/bootstrap';
import { clock } from '../observed';
import { useDrift } from './context';
import { RerunControl } from './ReadingControl';
import { lastRunLine, resultStale } from './result';
import { useRunBoard } from './useRunBoard';

/* The Drift card header's account of the stored reading: its model and "Analysis last run HH:MM", whether new
   work or a changed intent has left it behind, and the control that reads again. They stand together on one
   line because they are one fact: this is what was read, this is what has happened since, and this is the way
   to read it again. Drawn only where a stored reading this build can read stands: a refused or malformed one
   says so in its own section, and a last run nothing shows would point at nothing. While an analysis runs the
   last result stays in view, dimmed, so the header keeps naming it. */
export function DriftStamp() {
  const { model } = useDrift();
  const { annotate, raw, shape, annotation, entries } = model;
  const { board } = useRunBoard();
  if (!annotate || !raw || !shape || shape.malformed || !annotation) return null;
  const line = lastRunLine(shape.stamp, nextNumber(raw['read_at']));
  if (!line) return null;
  const stale = resultStale(shape, raw, annotation, entries);
  return (
    <div
      className="flex min-w-0 flex-col items-end gap-1 max-[760px]:items-start"
      data-next-drift-status
    >
      <div className="flex flex-wrap items-center justify-end gap-x-3 gap-y-1 max-[760px]:justify-start">
        <p
          className="m-0 text-label text-[var(--ink-label)] [font-family:var(--mono)]"
          data-next-drift-stamp
        >
          {line}
        </p>
        {stale ? (
          <p
            className="m-0 text-label font-semibold text-[var(--amber)] [font-family:var(--mono)]"
            data-next-result-stale={stale.kind}
          >
            {stale.before !== null
              ? `This check is from before your ${clock(stale.before)} message.`
              : stale.head}
          </p>
        ) : null}
        <RerunControl board={board} stale={Boolean(stale)} />
      </div>
      {stale?.superseded ? (
        <p className="m-0 max-w-[var(--measure)] text-label text-muted-foreground">
          {stale.superseded}
        </p>
      ) : null}
    </div>
  );
}
