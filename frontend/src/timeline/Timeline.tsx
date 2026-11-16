import { nativeSession } from '../observed/native';
import { Alert } from '../ui/alert';
import { useEffect, useMemo } from 'react';
import { nextFiniteNumber } from '../api/bootstrap';
import { exactIdentity } from '../api/identity';
import type { SessionIdentity } from '../api/types';
import { Disclosure } from '../controls/Disclosure';
import { useDisplayed, useShell } from '../shell/context';
import { selectContextRead, selectHarnessSources } from '../store/selectors';
import { ActivityFilter } from './ActivityFilter';
import { EventRow } from './EventRow';
import { LaneLegend, UnboundContext } from './Lanes';
import { eventFlows } from './rails';
import { useTimelineMode } from './modes';
import { timelineDisclosureKey, timelineFocusKey, type RowScope } from './scope';
import {
  eventsForMode,
  historyEmptyText,
  type Delegation,
  type GraphMode,
  type Lane,
  type TimelineEvent,
} from './semantic';
import { deriveView } from './view';
import './timeline.css';

/* The Decisions panel of a project, ported from `nextCockpitTimeline` and `projectSemanticTimeline`. */
const PRIMARY_DIRECTIONS = 5;

export interface TimelineProps {
  /** The route's project label. It scopes the activity filter and every disclosure, so projects never share either. */
  readonly project: string;
  /** The stable project key the context is read by, which is not always the label. */
  readonly projectKey: string;
  /** The focused session by exact harness and sid, or null at project scope. `state` decides whether a final output is yet a result. */
  readonly focus: (SessionIdentity & { readonly state?: string }) | null;
  /** The project's sessions. They name the First Officer lanes when no session is focused. Pass a list that is stable while the sessions are, because a new list rebuilds the model. */
  readonly sessions: readonly SessionIdentity[];
  /** Workers delegated to, from the delegated-work lanes; absent until that step supplies them. */
  readonly delegations?: readonly Delegation[];
  /** What an untouched panel shows before the reader chooses. The Decisions tab passes "decisions"; the shared default is "active". */
  readonly defaultMode?: GraphMode;
}

function clock(seconds: number): string {
  const date = new Date(seconds * 1000);
  return `${String(date.getHours()).padStart(2, '0')}:${String(date.getMinutes()).padStart(2, '0')}`;
}

function Rows({
  events,
  scope,
  generated,
  harnessLabels,
  lanes,
}: {
  readonly events: readonly TimelineEvent[];
  readonly scope: RowScope;
  readonly generated: number | null;
  readonly harnessLabels: ReadonlyMap<string, string>;
  readonly lanes: readonly Lane[];
}) {
  // Over every row the mode kept, in drawn order, so the rows folded into "Earlier meaningful" still join
  // their lane's line to the ones above them.
  const flows = eventFlows(events);
  const seenLanes = new Set<string>();
  const seenIds = new Map<string, number>();
  let directions = 0;
  let splitAt = events.length;
  events.forEach((event, index) => {
    if (event.kind !== 'direction') return;
    directions += 1;
    if (directions === PRIMARY_DIRECTIONS + 1 && splitAt === events.length) splitAt = index;
  });
  const rows = events.map((event, index) => {
    const first = !seenLanes.has(event.lane.key);
    seenLanes.add(event.lane.key);
    // A repeated fact id is still two rows, and React needs two keys; the disclosure state stays by id.
    const seen = seenIds.get(event.eventId) ?? 0;
    seenIds.set(event.eventId, seen + 1);
    return (
      <EventRow
        key={`${event.eventId}#${String(seen)}`}
        event={event}
        scope={scope}
        first={first}
        generated={generated}
        harnessLabels={harnessLabels}
        lanes={lanes}
        flows={flows[index] ?? new Map()}
      />
    );
  });
  const earlier = rows.slice(splitAt);
  return (
    <>
      {rows.slice(0, splitAt)}
      {earlier.length ? (
        <Disclosure
          disclosureKey={timelineDisclosureKey(scope, 'earlier-meaningful-events')}
          focusKey={timelineFocusKey(scope, 'earlier-meaningful-events')}
          summary={`Earlier meaningful · ${String(earlier.length)}`}
          className="pc-history-band"
        >
          {earlier}
        </Disclosure>
      ) : null}
    </>
  );
}

export function Timeline({
  project,
  projectKey,
  focus,
  sessions,
  delegations,
  defaultMode,
}: TimelineProps) {
  const { runtime } = useShell();
  const snapshot = useDisplayed((current) => current);
  const exact = focus ? exactIdentity(focus) : null;
  const focusHarness = exact?.harness ?? null;
  const focusSid = exact?.sid ?? null;
  const session = exact ? `${exact.harness}:${exact.sid}` : null;
  const generated = snapshot.data?.generated;
  const revision = nextFiniteNumber(generated);

  /* Passive reads, and the only thing this component starts. The runtime makes a repeat for a revision it has
     already settled a no-op, which is what keeps StrictMode and a remount from reading twice. */
  // biome-ignore lint/correctness/useExhaustiveDependencies: revision is the refetch trigger, not a value the body reads.
  useEffect(() => {
    runtime.loadContext({ projectKey, focus: null });
    if (focusHarness !== null && focusSid !== null)
      runtime.loadContext({ projectKey, focus: { harness: focusHarness, sid: focusSid } });
  }, [runtime, projectKey, focusHarness, focusSid, revision]);

  const [mode, setMode] = useTimelineMode({
    project,
    session,
    ...(defaultMode ? { defaultMode } : {}),
  });
  const scope: RowScope = useMemo(() => ({ project, session }), [project, session]);
  const read = useMemo(
    () =>
      selectContextRead(
        snapshot,
        projectKey,
        focusHarness !== null && focusSid !== null
          ? { harness: focusHarness, sid: focusSid }
          : null,
      ),
    [snapshot, projectKey, focusHarness, focusSid],
  );
  const entry = read.entry;
  const projectEntry = read.projectEntry;

  const entryData = read.shows ? (entry?.data ?? null) : null;
  const projectData = projectEntry?.data ?? null;
  const focusState = focus ? (nativeSession(focus).state ?? null) : null;
  const view = useMemo(
    () =>
      entryData
        ? deriveView({
            data: entryData,
            projectData,
            focusHarness,
            focusSid,
            focusState,
            sessions,
            delegations,
          })
        : null,
    [entryData, projectData, focusHarness, focusSid, focusState, sessions, delegations],
  );

  const harnessLabels = useMemo(() => {
    const labels = new Map<string, string>();
    for (const harness of selectHarnessSources(snapshot).rows)
      if (harness.key && harness.label) labels.set(harness.key, harness.label);
    return labels;
  }, [snapshot]);

  const heading = mode === 'decisions' ? 'RECORDED DECISIONS' : 'SEMANTIC TIMELINE';
  if (!read.shows || !view) {
    return (
      <section className="next-cockpit-semantic" data-next-cockpit-semantic>
        <h2>SEMANTIC TIMELINE</h2>
        <p className="next-cockpit-empty">
          {read.state === 'unavailable'
            ? 'Semantic context unavailable.'
            : 'Loading semantic context…'}
        </p>
      </section>
    );
  }
  const events = eventsForMode(view.model, view.registry, mode, view.focus);
  return (
    <section className="next-cockpit-semantic" data-next-cockpit-semantic>
      {read.state === 'stale' ? (
        <Alert
          as="p"
          variant="timeline-stale"
          announce={false}
          className="next-cockpit-stale-read"
          data-next-cockpit-stale-read
        >
          {entry?.revision
            ? `Last read ${clock(entry.revision)}. Refresh has failed since; these are the rows from that read.`
            : 'Refresh has failed since the last successful read; these are the rows from it.'}
        </Alert>
      ) : null}
      <h2>{heading}</h2>
      <section
        className="pc-semantic-timeline"
        data-order="newest-first"
        data-model="fact-projection"
        data-graph-layout="fo-task-lanes"
        data-graph-mode={mode}
      >
        <ActivityFilter mode={mode} onChoose={setMode} />
        {events.length ? (
          <>
            <LaneLegend lanes={view.registry.lanes} />
            <Rows
              events={events}
              scope={scope}
              generated={
                typeof generated === 'number' && Number.isFinite(generated) ? generated : null
              }
              harnessLabels={harnessLabels}
              lanes={view.registry.lanes}
            />
          </>
        ) : (
          <p className="pc-substrate-empty">{historyEmptyText(view.model, mode)}</p>
        )}
        <UnboundContext contributors={view.registry.unboundContributors} scope={scope} />
      </section>
    </section>
  );
}
