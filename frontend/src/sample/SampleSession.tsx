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
import { heldPosition, type HeldAt } from './held';

const HELD_SENTENCE = 'View only: this sample cannot be edited, saved or run.';
const HELD_MS = 5000;

function Banner() {
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
        About ninety minutes of an anonymized Claude Code session, an agent burning down a
        milestone, with its real stored summary and drift reading, so you can see what the Session
        page and Intent and drift show. Nothing here is saved, sent or run. Hover or press the
        numbered (i) marks for a short tour.
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
    </Card>
  );
}

/* Why a press did nothing, drawn where the reader pressed. It sat in the banner once, about 3,000 px above
   Delete summary, so a held press there looked dead; then at the foot of the viewport, where it covered the
   Copy button beside the press (usability review, 2026-10-20). It is drawn just under the refused control,
   inside the sample's own box, and only while held. */

function Held({ at }: { readonly at: HeldAt | null }) {
  return (
    <p
      role="status"
      className={
        at
          ? 'absolute z-10 m-0 max-w-[min(28rem,calc(100%-16px))] rounded-card border border-solid border-[var(--amber)] bg-card px-[12px] py-[8px] text-[var(--amber)]'
          : 'm-0'
      }
      style={at ?? undefined}
      data-sample-held
    >
      {at ? HELD_SENTENCE : ''}
    </p>
  );
}

/* The sample session, drawn by the page's own Session view over a shell of its own. Its board, its context
   and its record come from the fixture and nothing it does is written anywhere. */
export function SampleSession({ children }: { readonly children: ReactNode }) {
  const page = useShell();
  const fixture = use(SampleFixtureContext);
  const [shell] = useState(() => createSampleShell(page, fixture));
  const [held, setHeld] = useState<HeldAt | null>(null);
  const box = useRef<HTMLElement>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  useBoardRuntime(shell.runtime);
  // `useBoardRuntime` releases the runtime on unmount and tolerates a second mount, so the shell is not
  // disposed here: StrictMode's simulated unmount would otherwise end it before it ever read.
  useEffect(() => () => clearTimeout(timer.current), []);
  const onHeld = (control: Element) => {
    const node = box.current;
    setHeld(
      node
        ? heldPosition(
            control.getBoundingClientRect(),
            node.getBoundingClientRect(),
            window.innerHeight,
          )
        : { top: 0, left: 8 },
    );
    clearTimeout(timer.current);
    timer.current = setTimeout(() => setHeld(null), HELD_MS);
  };
  return (
    <ShellContext value={shell}>
      <ControlsProvider controls={shell.controls}>
        <TourContext value>
          <section ref={box} className="relative" data-sample-session>
            <Banner />
            <ViewOnly onHeld={onHeld}>{children}</ViewOnly>
            <Held at={held} />
          </section>
        </TourContext>
      </ControlsProvider>
    </ShellContext>
  );
}
