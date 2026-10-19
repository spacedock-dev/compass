import { createBrowserEnvironment } from '../transport/browser';
import type { EventSourceLike } from '../transport/ports';
import { createShell } from '../shell/createShell';
import type { Shell } from '../shell/context';
import { SAMPLE_FIXTURE, type SampleFixture } from './fixture';
import { createSampleBackend } from './memoryBackend';
import { createSampleFetch } from './sampleFetch';

/* A stream that is open and never says anything: the sample has no server to push, and a stream that
   exists keeps the page's polling at its slow rate instead of its fallback one. */
class QuietStream implements EventSourceLike {
  readonly readyState = 1;
  close(): void {
    /* Nothing was opened. */
  }
  addEventListener(): void {
    /* Nothing is ever sent. */
  }
}

/* The sample's own time. Its board was captured at one moment and every age on the page ("1m ago", "started
   about 11m ago") is measured from `generated`, so the sample's clock starts there and runs on from it: the page
   reads as it did when the reading was taken, on any day, instead of "154d ago". */
const startedAt = Date.now();
function sampleClock(fixture: SampleFixture): () => number {
  return () => Number(fixture.board['generated']) * 1000 + (Date.now() - startedAt);
}

/* The sample session's own shell: its own runtime, store, display gate and controls over an in-memory
   server and in-memory storage, so it cannot read, write or poll anything the page is showing. It speaks
   through the page's live regions and navigates with the page's router, which are the two things a reader
   of the sample shares with the rest of the page. */
export function createSampleShell(page: Shell, fixture: SampleFixture = SAMPLE_FIXTURE): Shell {
  return createShell({
    env: createBrowserEnvironment({
      window,
      document,
      EventSource: QuietStream,
      now: sampleClock(fixture),
    }),
    fetch: createSampleFetch(fixture),
    provider: createSampleBackend(),
    events: { addEventListener: () => undefined, removeEventListener: () => undefined },
    search: '',
    doc: null,
    router: page.router,
    announcer: page.announcer,
    host: { reload: () => undefined },
  });
}
