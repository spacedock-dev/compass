import { useEffect } from 'react';
import { installChoiceRelease } from '../controls/displayGate';
import { useBoardRuntime } from '../transport/hooks';
import { FALLBACK_POLL_MS, UNCOORDINATED_POLL_MS } from '../transport/live';
import { Breadcrumb } from './Breadcrumb';
import { useDisplayed, useRoute, useShell } from './context';
import { Header } from './Header';
import { shortcutTarget, SKIP_ROLE_SELECTOR } from './keyboard';
import { Notices } from './Notices';
import { findSession } from './derive';
import { selectObserved } from '../observed/select';
import { showFavicon, WAITING_TITLE_PREFIX } from './favicon';
import { documentTitle } from './title';
import { RoutedView } from './views';

/* The document's own keys, on the window rather than the document: a popover's Escape handler is a
   document listener, and one on the window runs after it, so "close this" comes before "leave this
   view" without either knowing about the other. */
function useShellKeyboard(): void {
  const { router } = useShell();
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      const target = event.target instanceof Element ? event.target : null;
      const editable = target instanceof HTMLElement && target.isContentEditable;
      const move = shortcutTarget(
        {
          key: event.key,
          tagName: target?.tagName ?? 'BODY',
          isContentEditable: editable,
          role: target?.closest(SKIP_ROLE_SELECTOR)?.getAttribute('role') ?? null,
          metaKey: event.metaKey,
          ctrlKey: event.ctrlKey,
          altKey: event.altKey,
          defaultPrevented: event.defaultPrevented,
        },
        router.getRoute(),
      );
      if (!move) return;
      event.preventDefault();
      router.navigate(move);
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [router]);
}

export function Page() {
  const { runtime, display, clock, host } = useShell();
  useBoardRuntime(runtime);
  useShellKeyboard();
  /* A Select popup closing is the reader's own moment: the newest deferred poll shows once. */
  useEffect(() => installChoiceRelease(document, display), [display]);

  const route = useRoute();
  const snapshot = useDisplayed((current) => current);
  const model = useDisplayed(selectObserved);
  /* Resolved as the page resolves it, so a released id-only link (no harness) still finds its one session. */
  const shown =
    route.view === 'session'
      ? findSession(snapshot.data, route.project, route.harness, route.session)
      : null;
  const waiting =
    shown !== null &&
    model.sessions.some(
      (row) =>
        row.harness === String(shown.harness ?? '') &&
        row.sid === String(shown.sid ?? '') &&
        row.project === String(shown.project ?? '') &&
        (row.isNeeds || row.askKnown),
    );
  const title = `${waiting ? WAITING_TITLE_PREFIX : ''}${documentTitle(route, snapshot.data)}`;
  useEffect(() => {
    document.title = title;
    showFavicon(document, waiting);
  }, [title, waiting]);

  const retryMs = host.streamSupported ? FALLBACK_POLL_MS : UNCOORDINATED_POLL_MS;
  const scope =
    route.view === 'project'
      ? { project: route.project, scope: route.focus ?? null }
      : route.view === 'session'
        ? { project: route.project, scope: `${route.harness ?? ''}:${route.session}` }
        : { project: null, scope: null };

  return (
    <main id="app">
      <Header route={route} />
      <Breadcrumb route={route} />
      <Notices
        snapshot={snapshot}
        now={clock.now()}
        retryMs={retryMs}
        onRetry={() => void runtime.refresh({ manual: true })}
        onReload={host.reload}
        disclosureScope={scope}
      />
      <RoutedView route={route} />
    </main>
  );
}
