import { useEffect, useMemo, type ReactNode } from 'react';
import { nextFiniteNumber } from '../api/bootstrap';
import { compatSessKey, exactIdentity } from '../api/identity';
import type { SessionIdentity } from '../api/types';
import { Disclosure } from '../controls/Disclosure';
import { disclosureKey } from '../controls/disclosureStore';
import { type Row, selectObserved } from '../observed';
import { payloadSessions } from '../api/bootstrap';
import { useDisplayed, useShell } from '../shell/context';
import { RouteLink } from '../shell/RouteLink';
import { Tripwires } from '../steering/Tripwires';
import { contextKey } from '../api/identity';
import { selectHarnessSources } from '../store/selectors';
import { TerminalSurface, useBridgeReading } from '../terminal';
import { ScopeCue } from '../timeline/ScopeCue';
import { CapacityPanel } from './CapacityPanel';
import { DelegationPanel } from './DelegationPanel';
import { useProjectWindow } from './evidence';
import { delegationFigure } from './metric';
import { consoleScope } from './scope';
import { WaitingPanel } from './WaitingPanel';
import './delegation.css';

export interface ProjectConsoleProps {
  /** The route's project label, exactly: it keys every disclosure and every draft here. */
  readonly project: string;
  /** The stable project key the context is read by, which is not always the label. */
  readonly projectKey: string;
  /** The exact selected session, or null at project scope. Never a display id. */
  readonly focus: (SessionIdentity & { readonly state?: string }) | null;
  /** The observer-model controls, drawn only when the capability is read as on. The capacity step supplies them. */
  readonly observer?: ReactNode;
  /** The usage disclosure and switch inside the capacity panel. The capacity step supplies them. */
  readonly usage?: (windows: boolean) => ReactNode;
}

type Reading = boolean | null | 'per-session';

/* One word per state, and four of them. "off" for a capability nothing has read yet is the confident wrong
   answer this board is built against; "not read yet" for one that nothing will ever read is the same error
   inverted. */
function said(value: Reading): string {
  if (value === true) return 'on';
  if (value === false) return 'off';
  return value === 'per-session' ? 'per-session' : 'not read yet';
}

/* The Console tab: the operations a reader came here to act on first, then the setup that describes what this
   server was started with. The rail leads, because an enabled capability is operational content and a
   disabled one is 300 pixels of text that never change while you work. Everything the rail draws is for the
   project, and the terminal and the observer controls are for the one exact session selected. Nothing here
   starts a model reading, a native action or a socket: the terminal opens on its own press, and the
   registration it reads is a passive lookup the surface performs. */
export function ProjectConsole({
  project,
  projectKey,
  focus,
  observer,
  usage,
}: ProjectConsoleProps) {
  const { runtime } = useShell();
  const snapshot = useDisplayed((current) => current);
  const model = selectObserved(snapshot);
  const observed = model.projects.find((candidate) => candidate.key === project);
  const identity = focus ? exactIdentity(focus) : null;
  const focusHarness = identity?.harness ?? null;
  const focusSid = identity?.sid ?? null;
  const revision = nextFiniteNumber(snapshot.data?.generated);

  /* A passive read, and the only thing this tab starts besides the terminal's own lookup. It is what the
     "observer model" half of the setup summary is read from; the runtime makes a repeat for a revision it
     has already settled a no-op, which is what keeps StrictMode and a remount from reading twice. */
  // biome-ignore lint/correctness/useExhaustiveDependencies: revision is the refetch trigger, not a value the body reads.
  useEffect(() => {
    runtime.loadContext({
      projectKey,
      focus:
        focusHarness !== null && focusSid !== null
          ? { harness: focusHarness, sid: focusSid }
          : null,
    });
  }, [runtime, projectKey, focusHarness, focusSid, revision]);

  const window = useProjectWindow(project);
  const figure = useMemo(() => delegationFigure(window), [window]);
  const labels = useMemo(() => {
    const map = new Map<string, string>();
    for (const harness of selectHarnessSources(snapshot).rows)
      if (harness.key && harness.label) map.set(harness.key, harness.label);
    return map;
  }, [snapshot]);
  const scope = consoleScope(focus ? { harness: focus.harness, sid: focus.sid } : null, labels);
  const terminal = useBridgeReading(identity);
  const entry = snapshot.contexts.get(contextKey(projectKey, identity));
  /* `undefined` is an entry that has not arrived; `null` from one that did is a read, and a read that
     published no observer model is a capability that is off. */
  const offer = entry?.data ? (entry.data.observer_model ?? null) : undefined;
  const observerReading: Reading = offer === undefined ? null : offer?.enabled === true;

  const members = payloadSessions(snapshot.data).rows.filter(
    (row) => String(row.project ?? '') === project,
  ) as unknown as readonly Row[];
  const only = members.length === 1 ? members[0] : undefined;
  const surface = identity ? <TerminalSurface project={project} identity={identity} /> : null;
  const scopeKey = focus ? compatSessKey(focus) : null;

  return (
    <>
      <header className="next-cockpit-scope next-cockpit-scope--evidence">
        <ScopeCue scope={scope} detail={scope.kind === 'session' ? scope.detail : undefined} />
        <strong>CONSOLE</strong>
      </header>
      {focus ? null : (
        <p className="next-cockpit-empty">
          Select one exact session to open its read-only console.
          {only ? (
            <>
              {' '}
              <RouteLink
                route={{
                  view: 'project',
                  project,
                  focus: compatSessKey(only),
                  tab: 'console',
                }}
              >
                Open this session’s console
              </RouteLink>
            </>
          ) : null}
        </p>
      )}
      {observed ? (
        <aside className="next-project-detail-rail" data-next-project-rail>
          <DelegationPanel figure={figure} />
          <WaitingPanel project={observed} />
          <CapacityPanel
            payload={(snapshot.data ?? {}) as Row}
            model={model}
            {...(usage === undefined ? {} : { usage })}
          />
          <Tripwires project={project} />
        </aside>
      ) : (
        <p className="next-absence">This project is not in the current payload.</p>
      )}
      {terminal === true ? surface : null}
      {observerReading === true ? observer : null}
      <Disclosure
        disclosureKey={disclosureKey({ project, scope: scopeKey, name: 'console-setup' })}
        summary={`How this server was started — terminal bridge ${said(terminal)}, observer model ${said(observerReading)}`}
        className="next-cockpit-console-setup"
      >
        {terminal === true ? null : surface}
        {observerReading === true ? null : observer}
        <RawStatus project={project} scope={scopeKey} members={members} />
      </Disclosure>
    </>
  );
}

function RawStatus({
  project,
  scope,
  members,
}: {
  readonly project: string;
  readonly scope: string | null;
  readonly members: readonly Row[];
}) {
  if (members.length === 0) return null;
  return (
    <Disclosure
      disclosureKey={disclosureKey({ project, scope, name: 'status' })}
      summary="Raw project status"
      className="next-cockpit-console-status"
    >
      <ul>
        {members.map((row, index) => (
          <li key={`${compatSessKey(row)}\u0000${String(index)}`}>
            {`${compatSessKey(row)} · ${String(row.state || 'unknown')}`}
          </li>
        ))}
      </ul>
    </Disclosure>
  );
}
