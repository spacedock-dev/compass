/* A development-only page that mounts the capacity strip, the usage consent and the observer-model controls
   over the REAL shell (runtime, store, router, controls, display gate), wired the way the page wires them:
   `<CapacityStrip />` is the Sessions view's last section, and the Console tab takes the usage disclosure and
   the observer controls through the typed slots `ProjectConsole` leaves for them. A browser test drives it
   against the real Python backend. It is not shipped: nothing in the production entry imports it, and the
   browser tests serve it by swapping `main.tsx` inside a scratch copy of the tree.

   The route decides what is on the page, as the real page does, so leaving and coming back is a real route
   change and a real unmount. */
import { StrictMode, useEffect } from 'react';
import { createRoot } from 'react-dom/client';
import { payloadSessions } from '../src/api/bootstrap';
import { compatSessKey, exactIdentity, stableProjectKey } from '../src/api/identity';
import { CapacityStrip, ObserverControls, RailUsage } from '../src/capacity';
import { ControlsProvider } from '../src/controls/ControlsProvider';
import { installChoiceRelease } from '../src/controls/displayGate';
import { ProjectConsole } from '../src/delegation';
import { ShellContext, useDisplayed, useRoute, useShell } from '../src/shell/context';
import { createShell } from '../src/shell/createShell';
import { useBoardRuntime } from '../src/transport/hooks';
import { replaceRuntime } from '../src/transport/runtime';
import '../src/styles/shell.css';
import '../src/styles/controls.css';
import '../src/styles/tailwind.css';
import '../src/project/project.css';

// A test entry module that mounts itself and exports nothing, so fast refresh has no component to track.
// biome-ignore lint/style/useComponentExportOnlyModules: nothing is exported, as the note above says.
function Hosted() {
  const shell = useShell();
  useBoardRuntime(shell.runtime);
  useEffect(() => installChoiceRelease(document, shell.display), [shell]);
  const route = useRoute();
  const data = useDisplayed((snapshot) => snapshot.data);
  if (route.view === 'sessions') {
    return (
      <section id="sessions" data-view="sessions">
        <h1>Session operations</h1>
        <CapacityStrip />
      </section>
    );
  }
  if (route.view !== 'project') {
    return (
      <p id="elsewhere" data-view={route.view}>
        Elsewhere: {route.view}
      </p>
    );
  }
  const rows = payloadSessions(data).rows.filter(
    (row) => String(row.project ?? '') === route.project,
  );
  const focusRow = route.focus ? rows.find((row) => compatSessKey(row) === route.focus) : undefined;
  const identity = focusRow ? exactIdentity(focusRow) : null;
  const projectKey = stableProjectKey({ label: route.project, sessions: rows });
  const focus = identity ? { ...identity, state: String(focusRow?.state ?? '') } : null;
  return (
    <div id="hosted" data-project={route.project} data-focus={route.focus ?? ''}>
      <h1>{route.project}</h1>
      <ProjectConsole
        project={route.project}
        projectKey={projectKey}
        focus={focus}
        usage={(windows) => <RailUsage windows={windows} />}
        observer={<ObserverControls projectKey={projectKey} focus={identity} />}
      />
    </div>
  );
}

function mountHarness(root: HTMLElement): void {
  const shell = createShell();
  replaceRuntime(shell.runtime);
  const strict = new URLSearchParams(location.search).get('strict') !== '0';
  const page = (
    <ShellContext value={shell}>
      <ControlsProvider controls={shell.controls}>
        <main id="app">
          <nav aria-label="Primary">
            <a href="#n=sessions">Sessions</a>
            <a href="#n=projects">Elsewhere</a>
          </nav>
          <Hosted />
        </main>
      </ControlsProvider>
    </ShellContext>
  );
  createRoot(root).render(strict ? <StrictMode>{page}</StrictMode> : page);
  Object.assign(window, { __harness: { shell } });
}

const root = document.getElementById('root');
if (!root) throw new Error('The harness document is missing its root.');
mountHarness(root);
