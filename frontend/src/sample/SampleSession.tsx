import { use, useEffect, useRef, useState, type ReactNode } from 'react';
import { ControlsProvider } from '../controls/ControlsProvider';
import { Card } from '../ui/card';
import { RouteLink } from '../shell/RouteLink';
import { ShellContext, useShell } from '../shell/context';
import { useBoardRuntime } from '../transport/hooks';
import { SampleFixtureContext } from './fixture';
import { TourContext } from './tourContext';
import { createSampleShell } from './sampleShell';
import { TOUR } from './tour';
import { ViewOnly } from './ViewOnly';

const HELD_SENTENCE = 'View only: this sample cannot be edited, saved or run.';
const HELD_MS = 5000;

function Banner({ held }: { readonly held: boolean }) {
  return (
    <Card
      as="section"
      variant="session-current"
      className="mb-4 flex flex-col gap-2"
      data-sample-banner
      aria-label="Sample session"
    >
      <p className="m-0 flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <strong className="text-foreground">Sample session (view only)</strong>
        <RouteLink className="ml-3" route={{ view: 'sessions', project: null, session: null }}>
          Back to Sessions
        </RouteLink>
      </p>
      <p className="m-0 text-muted-foreground">
        An anonymized Claude Code session with a real stored reading, so you can see what the
        Session page and Intent and drift show. Nothing here is saved, sent or run. Hover or press
        the numbered (i) marks for a short tour.
      </p>
      <details data-sample-tour>
        <summary className="cursor-pointer text-muted-foreground">Read the tour as text</summary>
        <ol className="my-2 flex list-none flex-col gap-2 p-0">
          {TOUR.map((note, index) => (
            <li key={note.id}>
              <strong className="text-foreground">{`${String(index + 1)}. ${note.title}.`}</strong>{' '}
              <span className="text-muted-foreground">{note.body}</span>
            </li>
          ))}
        </ol>
      </details>
      <p role="status" className="m-0 min-h-[1.5em] text-[var(--amber)]" data-sample-held>
        {held ? HELD_SENTENCE : ''}
      </p>
    </Card>
  );
}

/* The sample session, drawn by the page's own Session view over a shell of its own. Its board, its context
   and its record come from the fixture and nothing it does is written anywhere. */
export function SampleSession({ children }: { readonly children: ReactNode }) {
  const page = useShell();
  const fixture = use(SampleFixtureContext);
  const [shell] = useState(() => createSampleShell(page, fixture));
  const [held, setHeld] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  useBoardRuntime(shell.runtime);
  // `useBoardRuntime` releases the runtime on unmount and tolerates a second mount, so the shell is not
  // disposed here: StrictMode's simulated unmount would otherwise end it before it ever read.
  useEffect(() => () => clearTimeout(timer.current), []);
  const onHeld = () => {
    setHeld(true);
    clearTimeout(timer.current);
    timer.current = setTimeout(() => setHeld(false), HELD_MS);
  };
  return (
    <ShellContext value={shell}>
      <ControlsProvider controls={shell.controls}>
        <TourContext value>
          <section data-sample-session>
            <Banner held={held} />
            <ViewOnly onHeld={onHeld}>{children}</ViewOnly>
          </section>
        </TourContext>
      </ControlsProvider>
    </ShellContext>
  );
}
