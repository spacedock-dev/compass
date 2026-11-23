import { useEffect, useId, useRef, useState, type ReactNode } from 'react';
import type { ApiClient } from '../api/client';
import type { ApiResult, SettingsBody } from '../api/types';
import { NotificationControl } from '../notify';
import { useShell } from '../shell/context';
import { Button } from '../ui/button';
import { Card } from '../ui/card';
import { Switch } from '../ui/switch';
import { AiUseSettings } from './AiUseSettings';
import { PullRequestReadSetting, UsageConsentSetting } from './Connections';
import { SettingsLimitsCard } from './SettingsLimitsCard';
import { SettingsRow } from './SettingsRow';
import { DashboardDataCard } from './YourDataCard';
import { fieldsOf, settingsBody } from './model';

export type SettingsClient = Pick<ApiClient, 'getSettings' | 'postSettings'>;

type Load =
  | { readonly state: 'loading' }
  | { readonly state: 'failed' }
  | { readonly state: 'ready'; readonly body: SettingsBody };

type Write = 'limits' | 'update';

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

const UPDATE_NAME = 'Look for new versions once a day';

function updateStatus(load: Load) {
  if (load.state === 'loading') return 'Reading the update check setting.';
  const update = load.state === 'ready' ? load.body.update_check : null;
  if (!update) return 'The update check setting is unavailable.';
  if (update.cli_disabled) return 'Update checks are off for this run (--no-update-check).';
  if (!update.default_enabled) return 'Update checks are off in this build.';
  return update.disabled ? 'Update checks are off.' : 'Asks spacedock.md at most once a day.';
}

export function SettingsScreen({
  client,
  aiUse,
  pullRequestRead,
  browserSettings,
  yourData,
}: {
  readonly client: SettingsClient;
  readonly aiUse?: (promptBytes: number | null) => ReactNode;
  readonly pullRequestRead?: ReactNode;
  readonly browserSettings?: ReactNode;
  readonly yourData?: ReactNode;
}) {
  const [load, setLoad] = useState<Load>({ state: 'loading' });
  const [pending, setPending] = useState<Write | null>(null);
  const [outcome, setOutcome] = useState<{ kind: Write; text: string } | null>(null);
  const [attempt, setAttempt] = useState(0);
  const write = useRef<AbortController | null>(null);
  const updateDescription = useId();

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

  async function send(kind: Write, values: Record<string, number | boolean | null>) {
    // Both controls write the same store and the reply carries its whole state.
    if (load.state !== 'ready' || write.current) return;
    const controller = new AbortController();
    write.current = controller;
    setPending(kind);
    setOutcome(null);
    const result = await client.postSettings({ values }, controller.signal);
    write.current = null;
    if (controller.signal.aborted) return;
    setPending(null);
    const body = result.kind === 'ok' ? settingsBody(result.body) : null;
    if (!body) {
      setOutcome({
        kind,
        text: refusal(result.kind === 'ok' ? { kind: 'malformed', status: result.status } : result),
      });
      return;
    }
    setLoad({ state: 'ready', body });
    setOutcome({
      kind,
      text: kind === 'limits' ? 'Limits saved.' : 'Update check preference saved.',
    });
  }

  const body = load.state === 'ready' ? load.body : null;
  const update = body?.update_check;
  return (
    <section
      className="next-view"
      data-next-view-body="settings"
      data-next-settings-state={load.state}
    >
      <div className="mx-auto w-full max-w-[47.5rem] pb-5">
        <h1>Settings</h1>
        <p className="m-0 text-body text-muted-foreground">Changes save as you make them.</p>
        {aiUse?.(body?.values['analyze_prompt_bytes'] ?? null)}
        <Card as="section" aria-labelledby="settings-connections" className="mt-4 p-0">
          <h2 id="settings-connections" className="m-0 px-4 pt-4 text-value font-bold sm:px-6">
            Connections
          </h2>
          <div className="[&>*+*]:[border-block-start:1px_solid_var(--rule)]">
            {pullRequestRead}
            <SettingsRow
              title={UPDATE_NAME}
              description={
                <>
                  <p id={updateDescription} className="m-0">
                    {updateStatus(load)}
                  </p>
                  <p role="status" className="m-0">
                    {outcome?.kind === 'update' ? outcome.text : ''}
                  </p>
                </>
              }
            >
              {update?.default_enabled && !update.cli_disabled ? (
                <Switch
                  aria-label={UPDATE_NAME}
                  aria-describedby={updateDescription}
                  checked={!update.disabled}
                  readOnly={pending !== null}
                  aria-disabled={pending !== null || undefined}
                  aria-busy={pending === 'update' || undefined}
                  onCheckedChange={(checked) => void send('update', { no_update_check: !checked })}
                />
              ) : null}
            </SettingsRow>
            {browserSettings}
          </div>
        </Card>
        {body ? (
          <SettingsLimitsCard
            fields={fieldsOf(body)}
            capacities={body.capacities}
            locked={pending !== null}
            onWrite={(values) => send('limits', values)}
            outcome={outcome?.kind === 'limits' ? outcome.text : ''}
          />
        ) : (
          <div className="mt-4">
            {load.state === 'loading' ? (
              <p className="next-absence">Reading the settings in force.</p>
            ) : (
              <>
                <p className="next-absence">
                  The prompt limits and update preference could not be read.
                </p>
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
            )}
          </div>
        )}
        {yourData}
      </div>
    </section>
  );
}

export function SettingsView() {
  const { runtime } = useShell();
  return (
    <SettingsScreen
      client={runtime.client}
      aiUse={(promptBytes) => <AiUseSettings promptBytes={promptBytes} />}
      pullRequestRead={<PullRequestReadSetting />}
      browserSettings={
        <>
          <NotificationControl />
          <UsageConsentSetting />
        </>
      }
      yourData={<DashboardDataCard client={runtime.client} />}
    />
  );
}
