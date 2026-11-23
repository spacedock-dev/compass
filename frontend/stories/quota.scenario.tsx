import { useEffect, useState } from 'react';
import { CapacityStrip } from '../src/capacity/CapacityStrip';
import { CapacityPanel } from '../src/delegation/CapacityPanel';
import { observe } from '../src/observed';
import { RailUsage } from '../src/capacity/UsageConsent';
import { createShell } from '../src/shell/createShell';
import { ShellContext } from '../src/shell/context';
import { createFakeClock, createFakeEnvironment } from '../src/transport/testing';
import { fakeBackend } from '../test/storage_backends';
import { ControlsProvider } from '../src/controls';

/* The quota fetch is on until the reader turns it off: one line says what is read and that no session content
   is sent, and one button turns it off. Every `/api/data` URL the page sends is kept, so the story asserts the
   request a press changes, not only the words. */
export const requests: string[] = [];
export let refreshQuota: (() => Promise<void>) | undefined;
export const CLAUDE_WINDOW = [
  { harness: 'claude', state: 'ok', asOf: 1, fiveH: { pct: 34, windowSec: 18000, resetAt: 9060 } },
];
export const CODEX_WINDOW = [
  { harness: 'codex', state: 'ok', asOf: 1, fiveH: { pct: 71, windowSec: 10800, resetAt: 9060 } },
];
const HARNESSES = [
  { key: 'claude', label: 'Claude Code' },
  { key: 'codex', label: 'Codex' },
];
export function QuotaExample({
  declined = false,
  strip = false,
  rail = false,
  usage = [],
  history = [],
}: {
  readonly declined?: boolean;
  readonly strip?: boolean;
  readonly rail?: boolean;
  readonly usage?: readonly unknown[];
  readonly history?: readonly unknown[];
}) {
  const railPayload = { generated: 1, harnesses: HARNESSES, usage };
  const [shell] = useState(() => {
    requests.length = 0;
    let generated = 1;
    const backend = fakeBackend(declined ? { 'compass.next.usage.consent': 'declined' } : {});
    const json = (body: unknown) => new Response(JSON.stringify(body), { status: 200 });
    return createShell({
      env: createFakeEnvironment({ clock: createFakeClock() }),
      provider: () => backend,
      events: { addEventListener: () => undefined, removeEventListener: () => undefined },
      search: '',
      doc: null,
      reducedMotion: () => true,
      fetch: async (url) => {
        if (url.startsWith('/api/data')) requests.push(url);
        return json({
          generated: generated++,
          sessions: [],
          harnesses: HARNESSES,
          usage_fetch: true,
          usage,
          history,
        });
      },
    });
  });
  useEffect(() => {
    const release = shell.runtime.acquire();
    void shell.runtime.refresh();
    refreshQuota = async () => {
      await shell.runtime.refresh({ manual: true });
    };
    return () => {
      release();
      shell.runtime.dispose();
      shell.display.dispose();
    };
  }, [shell]);
  return (
    <ShellContext.Provider value={shell}>
      <ControlsProvider controls={shell.controls}>
        {strip ? (
          <CapacityStrip />
        ) : rail ? (
          <CapacityPanel
            payload={railPayload}
            model={observe(railPayload)}
            usage={(windows) => <RailUsage windows={windows} />}
          />
        ) : (
          <RailUsage windows />
        )}
      </ControlsProvider>
    </ShellContext.Provider>
  );
}
