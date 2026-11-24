import { useDrift } from './context';
import { GLOSSARY } from '../language/glossary';
import type { Board } from './flip';
import { RerunControl, RunPress, WhatIsSent } from './ReadingControl';
import { checkProgressShown, routeRefusal } from './route';
import { useRunBoard } from './useRunBoard';
import { SCOPE } from './sentences';

/* One press in two places: the header and Is it on track? (owner, 2026-11-24). Both copies are `RunPress`, so
   they share the board's refusal, the pause, the daily cap, the pending key and the job: pressing either one
   leaves both busy, then both inert while the check runs, and no copy can start a call the other would refuse.
   `inCard` gives the card's copy its own focus key, falling back to the press's, and a quieter weight where the
   card already has its own primary. */
export function CheckProgressPress({
  board,
  inCard = false,
  primary = true,
}: {
  readonly board: Board;
  readonly inCard?: boolean;
  readonly primary?: boolean;
}) {
  const { model } = useDrift();
  const { shown, again } = checkProgressShown(model);
  if (!shown) return null;
  const key = model.key;
  const weight = primary ? 'primary' : 'secondary';
  if (again) {
    return (
      <RerunControl
        board={board}
        weight={weight}
        {...(inCard ? { focusKey: `reading-again-card:${key}` } : {})}
      />
    );
  }
  return (
    <RunPress
      board={board}
      weight={weight}
      label={GLOSSARY.checkProgress.plain}
      focusKey={inCard ? `reading-card:${key}` : `reading:${key}`}
      fallbackKey={`reading:${key}`}
    />
  );
}

/* The retry stays in the same place whether the last check describes current work or has gone out of date. */
export function DriftStamp() {
  const { model } = useDrift();
  const { board } = useRunBoard();
  if (!checkProgressShown(model).shown) return null;
  return (
    <div className="flex min-w-0 flex-col items-end gap-1" data-next-drift-status>
      <CheckProgressPress board={board} />
    </div>
  );
}

export function ProgressDisclosure() {
  const { model } = useDrift();
  if (model.job || (model.annotate && routeRefusal(model.payload, model.session))) return null;
  const again = Boolean(model.raw || model.annotation?.['reading_refused'] === true);
  return <WhatIsSent about={again ? '' : SCOPE} />;
}
