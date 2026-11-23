import { useEffect, useMemo, useState, type ReactNode } from 'react';
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
import {
  projectSessionGroups,
  projectSessionLabels,
  projectStateCounts,
  type ProjectSession,
} from './projectActivity';
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
  rows,
  labels,
  disclosure,
  open,
}: {
  readonly model: ProjectModel;
  readonly slots: ProjectSlots;
  readonly rows: readonly ProjectSession[];
  readonly labels: ReturnType<typeof projectSessionLabels>;
  readonly disclosure: string;
  readonly open: boolean;
}) {
  const context = slotContext(model);
  const [picked, setPicked] = useState('');
  const choices = rows.filter(({ identity }) => identity);
  const automatic = model.focusIdentity
    ? choices.find(
        ({ identity }) =>
          identity?.harness === model.focusIdentity?.harness &&
          identity?.sid === model.focusIdentity?.sid,
      )
    : choices.length === 1
      ? choices[0]
      : undefined;
  const row = picked ? choices.find(({ key }) => key === picked) : automatic;
  const focus = row?.identity ? { ...row.identity, state: row.session.state } : null;
  return (
    <TechnicalDetails
      disclosureKey={disclosure}
      caption="Workflow, evidence and read-only terminal"
    >
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
                value={row?.key ?? ''}
                onChange={(event) => setPicked(event.target.value)}
              >
                <option value="">Choose a session</option>
                {choices.map(({ key }) => {
                  const label = labels.get(key);
                  return label ? (
                    <option key={key} value={key}>
                      {[label.title, label.harness, label.detail].filter(Boolean).join(' · ')}
                    </option>
                  ) : null;
                })}
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
  const { controls, runtime } = useShell();
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

  const disclosure = disclosureKey({
    project: route.project,
    scope: null,
    name: 'project-technical',
  });
  const technicalOpen = useControlledDisclosureState(controls.disclosures, disclosure);
  const payload = model?.payload;
  const rows = useMemo(
    () => (payload ? (projectSessionGroups(payload).get(route.project) ?? []) : []),
    [payload, route.project],
  );

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
  const labels = projectSessionLabels(rows, model.harnesses);
  const countLine = [
    `${String(rows.length)} ${rows.length === 1 ? 'session' : 'sessions'}`,
    ...projectStateCounts(rows)
      .slice(0, 4)
      .flatMap(({ word, count }) => (count ? [`${String(count)} ${word.toLowerCase()}`] : [])),
  ].join(' · ');
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
            <h1 className="text-hero font-extrabold" data-authored>
              {model.group.label}
            </h1>
            <p className="next-project-detail-count">{countLine}</p>
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
        <ProjectSummary model={model} rows={rows} />
        <ProjectTabs
          route={route}
          cue={(name) => {
            const cue = tabCue(name, { changes: changes.changes.length, read: model.scopeRead });
            return cue ? <CueMark tab={name} cue={cue} /> : null;
          }}
        >
          {(current) => (
            <Panel tab={current} focused={focused} label={SHOWN[current]}>
              {current === 'now' ? (
                <ProjectOverview model={model} rows={rows} labels={labels} />
              ) : null}
              {current === 'course' ? (
                <CourseTab model={model} showEvidence={technicalOpen} />
              ) : null}
              {current === 'decisions'
                ? (slots.decisions?.(context) ?? <DefaultDecisions />)
                : null}
              {current === 'console' ? slots.console?.(context, 'usage') : null}
            </Panel>
          )}
        </ProjectTabs>
        <ProjectTechnical
          key={model.group.label}
          model={model}
          slots={slots}
          rows={rows}
          labels={labels}
          disclosure={disclosure}
          open={technicalOpen}
        />
      </article>
    </section>
  );
}
