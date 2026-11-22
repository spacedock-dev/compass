import { useEffect, type ReactNode } from 'react';
import { nextFiniteNumber } from '../api/bootstrap';
import type { ProjectRoute, ProjectTab } from '../router/grammar';
import { ProjectTabs } from '../shell/ProjectTabs';
import { useShell } from '../shell/context';
import { useProjectChanges } from '../workstream';
import { GoingOn, HowEnded } from './ActivityViews';
import { CourseTab } from './CoursePanel';
import { useProjectModel, type ProjectModel } from './model';
import { Value } from './parts';
import { PlanDisclosure, PlanStatus } from './PlanView';
import { RecoveryStrip } from './RecoveryStrip';
import { ScopeSwitcher, ScopeTree } from './ScopeNav';
import { DefaultConsole, DefaultDecisions } from './SlotPlaceholders';
import { PROJECT_SLOTS, slotContext, type ProjectSlots } from './slots';
import { cueGloss, cueMark, tabCue, tabLede, type TabCue as Cue } from './tabs';
import { viewingSession } from './scope';
// The scope cue's markers are the timeline's: one drawing of "project" and "session", wherever it appears.
import '../timeline/timeline.css';
import './project.css';

/* One project's page: its name and where it lives, the scopes it can be read at, the recovery strip, the
   steering bar the steering step draws, and the four tabs. Choosing a scope or a tab changes the route and
   nothing else: the strip, the tabs' cues and every panel stand on one model of one board, so they cannot
   disagree. The context reads this page makes are passive source reading, started per board revision and
   never by a press, a mount or a StrictMode pass that already has the answer. */

function CueMark({ tab, cue }: { readonly tab: ProjectTab; readonly cue: Cue }) {
  const variant =
    cue.state === 'pending'
      ? ' next-cockpit-tab-cue--pending'
      : cue.state === 'unobserved'
        ? ' next-cockpit-tab-cue--unobserved'
        : cue.state === 'unavailable'
          ? ' next-cockpit-tab-cue--unavailable'
          : '';
  return (
    <span
      className={`next-cockpit-tab-cue${variant}`}
      data-next-cockpit-tab-cue={cue.state}
      {...(cue.stale ? { 'data-next-cockpit-tab-stale': '' } : {})}
    >
      <span aria-hidden="true">{cueMark(cue)}</span>
      {cue.stale ? (
        <span className="next-cockpit-tab-cue-stale" aria-hidden="true">
          stale
        </span>
      ) : null}
      <span className="next-visually-hidden">{cueGloss(tab, cue)}</span>
    </span>
  );
}

function Panel({
  tab,
  focused,
  label,
  children,
}: {
  readonly tab: ProjectTab;
  readonly focused: boolean;
  readonly label: string;
  readonly children: ReactNode;
}) {
  return (
    <section className="next-cockpit-panel" data-next-cockpit-panel={tab} aria-label={label}>
      <p className="next-cockpit-lede">{tabLede(tab, focused)}</p>
      {children}
    </section>
  );
}

function Header({ model }: { readonly model: ProjectModel }) {
  const { observed } = model.group;
  return (
    <header className="next-project-detail-header">
      <h1 className="next-project-detail-name">{observed.key}</h1>
      <Value text={observed.scopeText} known={observed.scopeKnown} className="next-project-scope" />
      <p className="next-project-detail-count">{observed.countLine}</p>
      {observed.sharedLabelKnown ? (
        <p className="next-project-detail-collision">{observed.sharedLabelText}</p>
      ) : null}
    </header>
  );
}

export function ProjectDetail({
  route,
  slots = PROJECT_SLOTS,
}: {
  readonly route: ProjectRoute;
  readonly slots?: ProjectSlots;
}) {
  const { runtime } = useShell();
  const model = useProjectModel(route);
  const changes = useProjectChanges(route.project);
  const revision = nextFiniteNumber(model?.generated);
  const projectKey = model?.projectKey ?? '';
  const harness = model?.focusIdentity?.harness ?? null;
  const sid = model?.focusIdentity?.sid ?? null;
  const tab: ProjectTab = route.tab ?? 'now';
  // The focused read is the Course, Decisions and Console tabs' own, as in the legacy page: Now reads the project's.
  const wantsFocus = tab !== 'now';

  /* Passive reads, and the only thing this page starts. The runtime makes a repeat for a revision it has
     already settled a no-op, which is what keeps StrictMode, a remount and a tab change from reading twice. */
  // biome-ignore lint/correctness/useExhaustiveDependencies: revision is the refetch trigger, not a value the body reads.
  useEffect(() => {
    if (!model) return;
    runtime.loadContext({ projectKey, focus: null });
    if (wantsFocus && harness !== null && sid !== null)
      runtime.loadContext({ projectKey, focus: { harness, sid } });
  }, [runtime, model === null, projectKey, wantsFocus, harness, sid, revision]);

  if (!model) return null;
  const context = slotContext(model);
  const multiSession = model.group.sessions.length > 1;
  const focused = model.focus !== null;
  const conditions = slots.courseConditions?.(context) ?? null;
  const viewing = model.focus ? viewingSession(model.focus, model.group, model.harnesses) : null;
  return (
    <section data-next-view-body="project">
      <article className="next-project-detail" data-next-project-detail={model.group.label}>
        <Header model={model} />
        <div className={`next-cockpit-shell${multiSession ? '' : ' next-cockpit-shell--single'}`}>
          {multiSession ? (
            <>
              <ScopeTree model={model} />
              <ScopeSwitcher model={model} />
            </>
          ) : null}
          <div className="next-cockpit-content">
            {viewing && model.focus ? (
              <div
                className="next-cockpit-viewing-session"
                data-next-cockpit-viewing-session={String(
                  model.focus['sid']
                    ? `${String(model.focus['harness'] || '')}:${String(model.focus['sid'])}`
                    : '',
                )}
              >
                {viewing.label}
                {viewing.state ? (
                  <span data-next-project-focus-status>{` · ${viewing.state}`}</span>
                ) : null}
                {viewing.limit ? (
                  <div className="next-project-session-limit">{viewing.limit}</div>
                ) : null}
              </div>
            ) : null}
            <RecoveryStrip model={model} />
            {slots.steering?.(context) ?? null}
            <ProjectTabs
              route={route}
              cue={(name) => {
                const cue = tabCue(name, {
                  changes: changes.changes.length,
                  read: model.scopeRead,
                });
                return cue ? <CueMark tab={name} cue={cue} /> : null;
              }}
            >
              {(current) => {
                if (current === 'now')
                  return (
                    <Panel tab="now" focused={focused} label="Now">
                      <GoingOn model={model} />
                      <HowEnded model={model} />
                      <PlanStatus model={model} />
                      <PlanDisclosure model={model} />
                    </Panel>
                  );
                if (current === 'course')
                  return (
                    <Panel tab="course" focused={focused} label="Course">
                      <CourseTab model={model} conditions={conditions} />
                    </Panel>
                  );
                if (current === 'decisions')
                  return (
                    <Panel tab="decisions" focused={focused} label="Decisions">
                      {slots.decisions?.(context) ?? <DefaultDecisions />}
                    </Panel>
                  );
                return (
                  <Panel tab="console" focused={focused} label="Console">
                    {slots.console?.(context) ?? <DefaultConsole model={model} />}
                  </Panel>
                );
              }}
            </ProjectTabs>
          </div>
        </div>
      </article>
    </section>
  );
}
