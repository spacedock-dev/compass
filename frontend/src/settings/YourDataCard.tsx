import { useEffect, useId, useState } from 'react';
import { Disclosure, useControls } from '../controls';
import { GLOSSARY } from '../language/glossary';
import { Button } from '../ui/button';
import { Card } from '../ui/card';
import { Icon } from '../ui/icons';
import type { ApiClient } from '../api/client';

const DELETES = [
  'Observation history',
  'Recorded session ends',
  'Launcher parent declarations',
  'Stored session summaries',
  'Copied-correction digests',
  'Discard records',
  'Reading permission',
];

const KEEPS = [
  'Typed goals, outcome lines, readings and group labels',
  'Dismissals and read choices (Dismiss and Mark as read)',
  'Unexpired AI spend timestamps',
  'Records of typed commands that have already used AI',
];

function DataList({ title, items }: { readonly title: string; readonly items: readonly string[] }) {
  const id = useId();
  return (
    <div>
      <h4 className="m-0 font-semibold" id={id}>
        {title}
      </h4>
      <ul className="m-0 list-disc ps-5" aria-labelledby={id}>
        {items.map((item) => (
          <li key={item}>{item}</li>
        ))}
      </ul>
    </div>
  );
}

type Port = number | 'loading' | null;

export function YourDataCard({ port }: { readonly port: Port }) {
  const name = useId();
  const controls = useControls();
  const [note, setNote] = useState('');
  const stop = `spacedock-compass --port ${port} --stop`;
  const forget = `spacedock-compass --port ${port} --forget`;
  const copy = async () => {
    setNote('');
    try {
      const clipboard = controls.clipboard();
      if (!clipboard) throw new Error('Clipboard unavailable');
      await clipboard.writeText(`${stop}\n${forget}`);
      setNote('Commands copied.');
    } catch {
      setNote('Could not copy. Select the commands above to copy them.');
    }
  };

  return (
    <Card as="section" aria-labelledby={name} className="relative mt-4 p-4 sm:p-6">
      <div className="sm:pe-48">
        <h2 id={name} className="m-0 text-value font-bold">
          {GLOSSARY.yourData.plain}
        </h2>
        <p className="mt-1 mb-0 text-body text-muted-foreground">
          Goals, summaries and history Compass has kept on this computer.
        </p>
      </div>
      <Disclosure
        disclosureKey="settings:forget"
        searchable={false}
        summary={
          <>
            <Icon name="forget" /> Forget everything
          </>
        }
        triggerClassName="my-2 gap-2 rounded-control border border-solid border-[var(--line)] px-3 text-body font-semibold sm:absolute sm:inset-e-6 sm:top-6 sm:m-0 [&_[data-slot=disclosure-chevron]]:hidden"
      >
        <div className="mt-3 flex flex-col gap-3 rounded-card border border-solid border-[var(--rule)] bg-muted p-4 text-body">
          <h3 className="m-0 font-bold">Forget everything</h3>
          <p className="m-0 font-semibold">This cannot be undone.</p>
          <p className="m-0">
            Run these commands on the computer where Compass is running, using the same environment
            you started it with. Stop Compass first, then run Forget everything.
          </p>
          {typeof port === 'number' ? (
            <>
              <div className="select-text rounded-control bg-[var(--ink)] p-3 text-label text-[color:var(--on-accent)] [overflow-wrap:anywhere]">
                <div>{stop}</div>
                <div>{forget}</div>
              </div>
              <p className="m-0 text-label text-muted-foreground">
                If you started Compass with Python, replace spacedock-compass with the same Python
                command you used to start server.py.
              </p>
              <div className="flex flex-wrap items-center gap-2">
                <Button variant="copy" onClick={() => void copy()}>
                  Copy
                </Button>
                <span role="status" className="text-label">
                  {note}
                </span>
              </div>
            </>
          ) : (
            <p role="status" className="m-0">
              {port === 'loading'
                ? 'Reading the dashboard port.'
                : 'Compass could not read the dashboard port. Use the port you started it with.'}
            </p>
          )}
          <div className="grid gap-3 sm:grid-cols-2">
            <DataList title="Deletes" items={DELETES} />
            <DataList title="Keeps" items={KEEPS} />
          </div>
          <p className="m-0 text-label text-muted-foreground">
            AI use stays paused until you choose Resume AI use. Summaries stay off until you turn
            them on again.
          </p>
        </div>
      </Disclosure>
    </Card>
  );
}

export function DashboardDataCard({ client }: { readonly client: Pick<ApiClient, 'getHealth'> }) {
  const [port, setPort] = useState<Port>('loading');
  useEffect(() => {
    const controller = new AbortController();
    void client.getHealth(controller.signal).then((result) => {
      if (controller.signal.aborted) return;
      const answered = result.kind === 'ok' ? result.body?.port : null;
      setPort(
        typeof answered === 'number' &&
          Number.isInteger(answered) &&
          answered > 0 &&
          answered <= 65535
          ? answered
          : null,
      );
    });
    return () => controller.abort();
  }, [client]);
  return <YourDataCard port={port} />;
}
