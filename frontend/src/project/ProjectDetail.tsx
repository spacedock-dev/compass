import { useEffect, useState, type ReactNode } from 'react';
import { compatSessKey } from '../api/identity';
import { CopyStatusUpdate } from '../controls/CopyStatusUpdate';
import { TechnicalDetails } from '../controls/TechnicalDetails';
import { disclosureKey } from '../controls/disclosureStore';
import { useControlledDisclosureState } from '../controls/useDisclosureState';
import { SHOWN } from '../language/glossary';
import { useProjectBriefing } from '../shell/projectBriefing';
import { fieldBase } from '../ui/input';
import { ProjectOverview, ProjectSummary } from './ProjectOverview';
import { nextFiniteNumber } from '../api/bootstrap';
import type { ProjectRoute, ProjectTab } from '../router/grammar';
import { ProjectTabs } from '../shell/ProjectTabs';
import { useShell } from '../shell/context';
import { useProjectChanges } from '../workstream';
import { GoingOn, HowEnded } from './ActivityViews';
import { CourseTab } from './CoursePanel';
import { useProjectModel, type ProjectModel } from './model';
import { PlanDisclosure, PlanStatus } from './PlanView';
import { RecoveryStrip } from './RecoveryStrip';
import { DefaultConsole, DefaultDecisions } from './SlotPlaceholders';
import { PROJECT_SLOTS, slotContext, type ProjectSlots } from './slots';
import { cueGloss, cueMark, tabCue, tabLede, type TabCue as Cue } from './tabs';
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

function ProjectTechnical({
  model,
  slots,
}: {
  readonly model: ProjectModel;
  readonly slots: ProjectSlots;
}) {
  const { controls } = useShell();
  const key = disclosureKey({ project: model.group.label, scope: null, name: 'project-technical' });
  const open = useControlledDisclosureState(controls.disclosures, key);
  const context = slotContext(model);
  const [picked, setPicked] = useState('');
  const choices = [
    ...new Map(
      model.group.observed.sessions
        .filter((row) => row.harness && row.sid)
        .map((row) => [compatSessKey(row), row]),
    ).values(),
  ];
  const automatic = model.focusIdentity
    ? compatSessKey(model.focusIdentity)
    : choices.length === 1
      ? compatSessKey(choices[0])
      : '';
  const selection = picked || automatic;
  const row = choices.find((candidate) => compatSessKey(candidate) === selection);
  const focus = row ? { harness: row.harness, sid: row.sid, state: row.state } : null;
  return (
    <TechnicalDetails disclosureKey={key} caption="Workflow, evidence and read-only terminal">
      <RecoveryStrip model={model} />
      {slots.steering?.(context)}
      {slots.courseConditions?.(context)}
      <PlanStatus model={model} />
      <PlanDisclosure model={model} />
      <GoingOn model={model} />
      <HowEnded model={model} />
      {open ? (
        <>
          {choices.length > 1 ? (
            <label className="project-terminal-picker">
              Session for the read-only terminal
              <select
                className={fieldBase}
                value={row ? selection : ''}
                onChange={(event) => setPicked(event.target.value)}
              >
                <option value="">Choose a session</option>
                {choices.map((choice) => (
                  <option key={compatSessKey(choice)} value={compatSessKey(choice)}>
                    {choice.titleText} · {model.harnesses.get(choice.harness) ?? choice.harness}
                  </option>
                ))}
              </select>
            </label>
          ) : null}
          {slots.console?.({ ...context, focus }, 'technical') ?? <DefaultConsole model={model} />}
        </>
      ) : null}
    </TechnicalDetails>
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
  const briefing = useProjectBriefing(route);
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
  const focused = model.focus !== null;
  return (
    <section data-next-view-body="project">
      <article
        className="next-project-detail project-detail"
        data-next-project-detail={model.group.label}
      >
        <header className="project-detail-title">
          <div>
            <h1 data-authored>{model.group.label}</h1>
            <p className="next-project-detail-count">{model.group.observed.countLine}</p>
            {model.group.observed.sharedLabelKnown ? (
              <p>{model.group.observed.sharedLabelText}</p>
            ) : null}
          </div>
          <CopyStatusUpdate
            projectKey={model.projectKey}
            focus={model.focusIdentity}
            briefingText={briefing}
          />
        </header>
        <ProjectSummary model={model} />
        <ProjectTabs
          route={route}
          cue={(name) => {
            const cue = tabCue(name, { changes: changes.changes.length, read: model.scopeRead });
            return cue ? <CueMark tab={name} cue={cue} /> : null;
          }}
        >
          {(current) => (
            <Panel tab={current} focused={focused} label={SHOWN[current]}>
              {current === 'now' ? <ProjectOverview model={model} /> : null}
              {current === 'course' ? <CourseTab model={model} conditions={null} /> : null}
              {current === 'decisions'
                ? (slots.decisions?.(context) ?? <DefaultDecisions />)
                : null}
              {current === 'console' ? slots.console?.(context, 'usage') : null}
            </Panel>
          )}
        </ProjectTabs>
        <ProjectTechnical key={model.group.label} model={model} slots={slots} />
      </article>
    </section>
  );
}
