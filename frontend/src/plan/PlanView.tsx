import { useMemo } from 'react';
import { useDisplayed } from '../shell/context';
import { PlanPage, RefusedPlanPage } from './PlanPage';
import { planModel } from './model';

export function PlanView() {
  const plan = useDisplayed((snapshot) => snapshot.plan);
  const board = useDisplayed((snapshot) => snapshot.data);
  const model = useMemo(
    () => (plan?.state === 'ready' ? planModel(plan, board) : null),
    [plan, board],
  );
  return (
    <div className="[@media(max-width:760px)]:-mx-[18px]">
      {plan?.state === 'refused' ? (
        <RefusedPlanPage reason={plan.reason} />
      ) : (
        model && <PlanPage model={model} />
      )}
    </div>
  );
}
