import { useEffect, useRef, useState, type ReactNode } from 'react';
import type { ApiClient } from '../api/client';
import type { ApiResult, SettingsBody } from '../api/types';
import { useShell } from '../shell/context';
import { Button } from '../ui/button';
import { Label } from '../ui/label';
import { AiUseSettings } from './AiUseSettings';
import { SettingsLimitsCard } from './SettingsLimitsCard';
import { DashboardDataCard } from './YourDataCard';
import { fieldsOf, settingsBody } from './model';

export type SettingsClient = Pick<ApiClient, 'getSettings' | 'postSettings'>;

type Load =
  | { readonly state: 'loading' }
  | { readonly state: 'failed' }
  | { readonly state: 'ready'; readonly body: SettingsBody };

function refusal(result: Exclude<ApiResult<unknown>, { kind: 'ok' }>): string {
  if (result.kind === 'http-error' && result.status === 400)
    return 'The server refused the change. The previous setting is still in force.';
  if (result.kind === 'http-error' && result.status === 503)
    return 'The settings could not be written. Try again.';
  if (result.kind === 'http-error')
    return `The server refused the change (${String(result.status)}).`;
  if (result.kind === 'malformed')
    return 'Compass could not read the server’s answer. Reload to see the settings in force.';
  return 'Compass could not confirm the change. Reload to see the settings in force.';
}

export function SettingsScreen({
  client,
  aiUse,
  yourData,
}: {
  readonly client: SettingsClient;
  readonly aiUse?: ReactNode;
  readonly yourData?: ReactNode;
}) {
  const [load, setLoad] = useState<Load>({ state: 'loading' });
  const [pending, setPending] = useState<'limits' | 'update' | null>(null);
  const [outcome, setOutcome] = useState('');
  const [attempt, setAttempt] = useState(0);
  const write = useRef<AbortController | null>(null);

  // biome-ignore lint/correctness/useExhaustiveDependencies: Try again starts a new read.
  useEffect(() => {
    const controller = new AbortController();
    void client.getSettings({ signal: controller.signal }).then((result) => {
      if (controller.signal.aborted) return;
      const body = result.kind === 'ok' ? settingsBody(result.body) : null;
      setLoad(body ? { state: 'ready', body } : { state: 'failed' });
    });
    return () => controller.abort();
  }, [client, attempt]);

  useEffect(() => () => write.current?.abort(), []);

  async function send(kind: 'limits' | 'update', values: Record<string, number | boolean | null>) {
    // Both controls write the same store and the reply carries its whole state.
    if (load.state !== 'ready' || write.current) return;
    const controller = new AbortController();
    write.current = controller;
    setPending(kind);
    setOutcome('');
    const result = await client.postSettings({ values }, controller.signal);
    write.current = null;
    if (controller.signal.aborted) return;
    setPending(null);
    const body = result.kind === 'ok' ? settingsBody(result.body) : null;
    if (!body) {
      setOutcome(
        refusal(result.kind === 'ok' ? { kind: 'malformed', status: result.status } : result),
      );
      return;
    }
    setLoad({ state: 'ready', body });
    setOutcome(kind === 'limits' ? 'Limits saved.' : 'Update check preference saved.');
  }

  const settings = () => {
    if (load.state === 'loading')
      return <p className="next-absence">Reading the settings in force.</p>;
    if (load.state === 'failed')
      return (
        <>
          <p className="next-absence">The prompt limits and update preference could not be read.</p>
          <Button
            type="button"
            variant="retry"
            onClick={() => {
              setLoad({ state: 'loading' });
              setAttempt((count) => count + 1);
            }}
          >
            Try again
          </Button>
        </>
      );
    const fields = fieldsOf(load.body);
    const update = load.body.update_check;
    return (
      <>
        {update ? (
          <section
            className="mt-4 flex max-w-[var(--measure)] flex-col gap-2"
            aria-labelledby="update-check-heading"
          >
            <h2 id="update-check-heading" className="m-0 text-value font-bold">
              Updates
            </h2>
            <Label className="flex items-center gap-2 text-body">
              <input
                type="checkbox"
                checked={update.disabled}
                disabled={pending !== null}
                onChange={(event) =>
                  void send('update', { no_update_check: event.currentTarget.checked })
                }
              />
              Turn off daily update checks
            </Label>
            <p className="m-0 text-body text-muted-foreground">
              Checks spacedock.md at most once per UTC day for a newer release.
            </p>
            {!update.default_enabled ? (
              <p className="m-0 text-body text-muted-foreground">
                Update checks are off by default in this build.
              </p>
            ) : null}
            {update.cli_disabled ? (
              <p className="m-0 text-body text-muted-foreground">
                Update checks are off for this run (--no-update-check).
              </p>
            ) : null}
          </section>
        ) : null}
        <SettingsLimitsCard
          fields={fields}
          capacities={load.body.capacities}
          locked={pending !== null}
          onWrite={(values) => send('limits', values)}
          outcome={outcome}
        />
        <div className="mt-2 flex flex-wrap gap-2">
          <Button type="button" disabled>
            Save
          </Button>
          {fields.some((field) => field.value !== field.fallback) ? (
            <Button
              type="button"
              disabled={pending !== null}
              onClick={() =>
                void send('limits', Object.fromEntries(fields.map(({ key }) => [key, null])))
              }
            >
              Restore all defaults
            </Button>
          ) : null}
        </div>
      </>
    );
  };
  return (
    <section
      className="next-view"
      data-next-view-body="settings"
      data-next-settings-state={load.state}
    >
      <h1>Settings</h1>
      {aiUse}
      {settings()}
      {yourData}
    </section>
  );
}

export function SettingsView() {
  const { runtime } = useShell();
  return (
    <SettingsScreen
      client={runtime.client}
      aiUse={<AiUseSettings />}
      yourData={<DashboardDataCard client={runtime.client} />}
    />
  );
}
