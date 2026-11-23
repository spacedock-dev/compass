import { useId, useState } from 'react';
import { setCiRead } from '../api/readings';
import { useConsent, useUsageAnswer, useUsageOffered } from '../capacity/held';
import { CI_SWITCH_FAILED } from '../drift/sentences';
import { GLOSSARY } from '../language/glossary';
import { isRecord } from '../observed';
import { useDisplayed, useShell } from '../shell/context';
import { Button } from '../ui/button';
import { Switch } from '../ui/switch';
import { SettingsRow } from './SettingsRow';

type ReadSetting = 'on' | 'off' | 'flag-off';

const isReadSetting = (value: unknown): value is ReadSetting =>
  value === 'on' || value === 'off' || value === 'flag-off';

function publishedCiRead(routes: unknown): ReadSetting | null {
  if (!isRecord(routes)) return null;
  const states = new Set(
    Object.values(routes).flatMap((route) =>
      isRecord(route) && isReadSetting(route['ci_read']) ? [route['ci_read']] : [],
    ),
  );
  return states.size === 1 ? ([...states][0] ?? null) : null;
}

const PULL_REQUEST_STATUS = {
  on: 'Uses your GitHub or GitLab login when a progress check names a pull request.',
  off: 'Pull request reads are off.',
  'flag-off': 'Pull request reads are off for this run (--no-ci-read).',
};

export function PullRequestReadSetting() {
  const descriptionId = useId();
  const { runtime } = useShell();
  const board = useDisplayed((snapshot) => snapshot);
  const [receipt, setReceipt] = useState<{
    readonly value: ReadSetting;
    readonly acceptedCount: number;
  } | null>(null);
  const [failure, setFailure] = useState('');
  const pending = board.pending.includes('ci-read:settings');
  const shown =
    receipt && board.acceptedCount <= receipt.acceptedCount
      ? receipt.value
      : board.failures
        ? null
        : publishedCiRead(board.data?.reading_routes);
  const description = shown
    ? PULL_REQUEST_STATUS[shown]
    : board.failures
      ? 'Compass could not refresh the pull request read setting.'
      : 'The pull request read setting is unavailable.';
  const name = GLOSSARY.pullRequestRead.plain;
  async function change(on: boolean) {
    const token = runtime.pending.start('ci-read:settings', 'Saving…');
    if (!token) return;
    setFailure('');
    try {
      const result = await setCiRead(runtime.client, on ? 'on' : 'off', token.signal);
      const answer =
        result.kind === 'ok' && isRecord(result.body) && result.body['ok'] === true
          ? result.body['ci_read']
          : null;
      if (!isReadSetting(answer)) {
        setFailure(CI_SWITCH_FAILED);
        return;
      }
      // The write answers before the next board. A newer board takes over as soon as it arrives.
      setReceipt({ value: answer, acceptedCount: runtime.store.getSnapshot().acceptedCount });
      await runtime.refresh();
    } finally {
      runtime.pending.end('ci-read:settings', token);
    }
  }
  return (
    <SettingsRow
      title={name}
      description={
        <>
          <p id={descriptionId} className="m-0">
            {description}
          </p>
          <p className="m-0" role="status">
            {failure}
          </p>
        </>
      }
    >
      {shown === 'on' || shown === 'off' ? (
        <Switch
          aria-label={name}
          aria-describedby={descriptionId}
          checked={shown === 'on'}
          readOnly={pending}
          aria-disabled={pending || undefined}
          aria-busy={pending || undefined}
          onCheckedChange={(on) => void change(on)}
        />
      ) : null}
    </SettingsRow>
  );
}

export function UsageConsentSetting() {
  const answer = useUsageAnswer();
  const consent = useConsent('usage');
  const offered = useUsageOffered();
  const [failed, setFailed] = useState(false);
  const off = consent === 'declined';
  return (
    <SettingsRow
      title={GLOSSARY.settingsUsageConsent.plain}
      description={
        <>
          <p className="m-0">
            Reads your plan's usage with the sign-ins on this computer. No session content is sent.
            Kept in this browser.
          </p>
          <p className="m-0">
            {off
              ? 'Plan usage is turned off in this browser.'
              : offered
                ? 'Plan usage is allowed in this browser.'
                : 'Plan usage is unavailable on this dashboard.'}
          </p>
          <p role="status" className="m-0">
            {failed ? 'The browser kept this choice for this tab only.' : ''}
          </p>
        </>
      }
    >
      <Button
        type="button"
        aria-label={off ? 'Allow plan usage' : 'Turn off plan usage'}
        onClick={() => setFailed(!answer(off ? 'granted' : 'declined'))}
      >
        {off ? 'Allow' : 'Turn off'}
      </Button>
    </SettingsRow>
  );
}
