import { useDrift } from './context';
import { GLOSSARY } from '../language/glossary';
import { RerunControl, RunPress, WhatIsSent } from './ReadingControl';
import { routeRefusal } from './route';
import { useRunBoard } from './useRunBoard';
import { SCOPE } from './sentences';

/* The retry stays in the same place whether the last check describes current work or has gone out of date. */
export function DriftStamp() {
  const { model } = useDrift();
  const { board } = useRunBoard();
  const again = Boolean(model.raw || model.annotation?.['reading_refused'] === true);
  if ((model.annotate && routeRefusal(model.payload, model.session)) || (model.job && !again))
    return null;
  return (
    <div className="flex min-w-0 flex-col items-end gap-1" data-next-drift-status>
      {again ? (
        <RerunControl board={board} />
      ) : (
        <RunPress
          board={board}
          weight={model.unsettled ? 'secondary' : 'primary'}
          label={GLOSSARY.checkProgress.plain}
          focusKey={`reading:${model.key}`}
        />
      )}
    </div>
  );
}

export function ProgressDisclosure() {
  const { model } = useDrift();
  if (model.job || (model.annotate && routeRefusal(model.payload, model.session))) return null;
  const again = Boolean(model.raw || model.annotation?.['reading_refused'] === true);
  return <WhatIsSent about={again ? '' : SCOPE} />;
}
