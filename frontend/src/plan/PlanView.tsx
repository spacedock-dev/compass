import { useMemo } from 'react';
import { useDisplayed } from '../shell/context';
import { PlanPage, PlanReadFailed, RefusedPlanPage } from './PlanPage';
import { planModel } from './model';

export function PlanView() {
  const plan = useDisplayed((snapshot) => snapshot.plan);
  const board = useDisplayed((snapshot) => snapshot.data);
  const model = useMemo(
    () => (plan.state === 'ready' ? planModel(plan, board) : null),
    [plan, board],
  );
  return (
    /* Cancels the shell's side padding (shell.css: 18 px to 760 px wide, 8 px to 360 px) so Plan keeps
       its one 16 px gutter. The ranges do not overlap, so the order Tailwind prints them in cannot matter. */
    <div className="[@media(width>360px)_and_(width<=760px)]:-mx-[18px] [@media(width<=360px)]:-mx-[8px]">
      {plan.state === 'refused' ? (
        <RefusedPlanPage reason={plan.reason} />
      ) : plan.state === 'failed' ? (
        <PlanReadFailed />
      ) : (
        model && <PlanPage model={model} />
      )}
    </div>
  );
}
