import { Disclosure, disclosureKey } from '../controls';
import { Icon } from '../ui/icons';
import type { ProjectModel } from './model';
import {
  entityState,
  planBlock,
  planOffered,
  projectPlans,
  unhealthyCount,
  type Plan,
  type WorkflowDefinition,
} from './plans';
import { semanticObservation } from './panels';

/* The project's plan, from what the working sessions published (live plans) or what Spacedock discovery
   found on disk (declared workflows), or why neither. Nothing is estimated: the status line says the
   estimate is withheld, and an entity is "unhealthy" only on a published reason (blocked on the reader, or
   its session quiet past one token-rate window). Ported from `next-project.js`. */

function PlanRows({ plan, model }: { readonly plan: Plan; readonly model: ProjectModel }) {
  return (
    <section className="next-project-plan" data-next-plan={plan.name}>
      <header>
        <span>PLAN</span>
        <strong>{plan.name}</strong>
        {plan.goal ? <p>{plan.goal}</p> : null}
      </header>
      <div className="next-project-plan-rows">
        {plan.entities.map((entity) => {
          const state = entityState(entity, model.generated);
          const harness = String(entity.session['harness'] || '');
          const owner = entity.live ? model.harnesses.get(harness) || harness : '';
          return (
            <div
              key={entity.slug}
              className={`next-project-plan-row${entity.live ? '' : ' next-project-plan-row--pending'}${state.unhealthy ? ' next-project-plan-row--unhealthy' : ''}`}
              data-next-plan-entity={entity.slug}
              data-next-live={String(entity.live)}
            >
              <Icon
                name={entity.live ? 'working' : 'unrecorded'}
                className="next-project-plan-glyph shrink-0"
              />
              <span className="next-project-plan-step">
                <strong>{entity.slug}</strong>
                {entity.cycle ? (
                  <span className="next-project-plan-cycle">{entity.cycle}</span>
                ) : null}
                <small>{entity.stage}</small>
              </span>
              <span className="next-project-plan-owner">{owner}</span>
              <span className="next-project-plan-state">
                <span data-next-plan-status>
                  {entity.live ? 'Live' : 'Pending'}
                  {state.label ? ' · ' : ''}
                </span>
                {state.label}
              </span>
            </div>
          );
        })}
      </div>
    </section>
  );
}

function Definition({ workflow }: { readonly workflow: WorkflowDefinition }) {
  return (
    <section
      className="next-project-workflow-definition"
      data-next-workflow-definition={workflow.name}
    >
      <header>
        <span>PROJECT WORKFLOW</span>
        <strong>{workflow.name}</strong>
        {workflow.goal ? <p>{workflow.goal}</p> : null}
      </header>
      <div className="next-project-workflow-stages">
        <span>DECLARED STAGES</span>
        <strong>
          {workflow.stages.length ? workflow.stages.join(' · ') : 'definition unavailable'}
        </strong>
      </div>
      <small>Observed by Spacedock project discovery; no live entity state is inferred.</small>
    </section>
  );
}

export function PlanBlockView({ model }: { readonly model: ProjectModel }) {
  const observation = semanticObservation(model);
  const plans = projectPlans(model.group.sessions);
  const block = planBlock(plans, model.group.sessions, observation);
  if (block.kind === 'plans')
    return (
      <>
        {block.plans.map((plan) => (
          <PlanRows key={plan.name} plan={plan} model={model} />
        ))}
      </>
    );
  if (block.kind === 'definitions')
    return (
      <>
        {block.workflows.map((workflow, index) => (
          <Definition key={`${workflow.name}#${String(index)}`} workflow={workflow} />
        ))}
      </>
    );
  return <div className="next-project-detail-empty">{block.text}</div>;
}

/** "N entities unhealthy — estimate withheld", only where there is a plan to be unhealthy. */
export function PlanStatus({ model }: { readonly model: ProjectModel }) {
  const plans = projectPlans(model.group.sessions);
  if (!plans.length) return null;
  const unhealthy = unhealthyCount(plans, model.generated);
  return (
    <div className="next-project-detail-status">
      <span data-next-withheld="">no estimate left · no confidence</span>
      <p>
        {`${String(unhealthy)} ${unhealthy === 1 ? 'entity' : 'entities'} unhealthy — `}
        <span data-next-withheld="">estimate withheld</span>
      </p>
    </div>
  );
}

export function PlanDisclosure({ model }: { readonly model: ProjectModel }) {
  const plans = projectPlans(model.group.sessions);
  if (!planOffered(plans, model.group.sessions, semanticObservation(model))) return null;
  return (
    <Disclosure
      disclosureKey={disclosureKey({
        project: model.route.project,
        scope: model.route.focus ?? '',
        name: 'plan',
      })}
      className="next-cockpit-plan-details"
      focusKey="cockpit-disclosure:plan"
      summary="Show project plan"
    >
      <div>
        <PlanBlockView model={model} />
      </div>
    </Disclosure>
  );
}
