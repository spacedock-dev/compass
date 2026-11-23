import { useId } from 'react';
import { parseGrant } from '../api/summary';
import { Disclosure } from '../controls';
import { GLOSSARY } from '../language/glossary';
import { isRecord } from '../observed';
import { setSummaries } from '../sessions/summaryActions';
import { grantShown, summaryHeldFor, useSummaryHeld } from '../sessions/summaryHeld';
import { useDisplayed, useShell } from '../shell/context';
import { Card } from '../ui/card';
import { Switch } from '../ui/switch';
import { AiPauseSwitch } from './AiPauseSwitch';
import { kilobytes } from './model';
import { SettingsRow } from './SettingsRow';

function SummariesSwitch({ paused }: { readonly paused: boolean | null }) {
  const descriptionId = useId();
  const shell = useShell();
  const data = useDisplayed((snapshot) => snapshot.data);
  const pending = useDisplayed((snapshot) => snapshot.pending.includes('summary-grant:settings'));
  const held = summaryHeldFor(shell.runtime);
  const note = useSummaryHeld(held, 'settings');
  const grant = grantShown(held, parseGrant(data?.['summaries']), Number(data?.generated ?? 0));
  const available = paused !== null && grant && grant.reason !== 'store-unavailable';
  const on = available && !paused && !grant.off;
  const words = paused
    ? 'Paused while AI use is paused.'
    : !available
      ? 'The Summaries setting is unavailable.'
      : grant.off
        ? 'Summaries are off.'
        : grant.reason === 'daily-cap'
          ? 'Summaries are on. Today’s limit has been reached.'
          : 'Summaries are on.';
  return (
    <div className="ms-4 [border-inline-start:1px_solid_var(--rule)] sm:ms-6">
      <SettingsRow
        title="Summaries"
        description={
          <>
            <p className="m-0">
              Write a short summary when you open a finished Claude Code session.
            </p>
            <p id={descriptionId} className="m-0">
              {words}
            </p>
            <p className="m-0" role="status">
              {note.failed}
            </p>
          </>
        }
      >
        {available ? (
          <Switch
            aria-label="Summaries"
            aria-describedby={descriptionId}
            aria-disabled={paused || pending || undefined}
            aria-busy={pending || undefined}
            readOnly={paused || pending || false}
            checked={Boolean(on)}
            onCheckedChange={(next) => void setSummaries(shell, null, next)}
          />
        ) : null}
      </SettingsRow>
    </div>
  );
}

function WhatIsSent({ promptBytes }: { readonly promptBytes: number | null }) {
  const board = useDisplayed((snapshot) => (snapshot.failures ? null : snapshot.data));
  const summary = parseGrant(board?.['summaries']);
  const routes = board?.reading_routes;
  const destinations = isRecord(routes)
    ? [
        ...new Set(
          Object.values(routes).flatMap((route) => {
            if (!isRecord(route)) return [];
            const destination = route['words_destination'] || route['destination'];
            return typeof destination === 'string' && destination.trim() ? [destination] : [];
          }),
        ),
      ]
    : [];
  return (
    <Disclosure
      explanation
      disclosureKey="settings:what-is-sent"
      searchable={false}
      summary="What is sent, and where"
    >
      <div className="grid gap-3 pb-3 text-body text-muted-foreground">
        <div>
          <h3 className="m-0 text-body font-semibold text-foreground">Progress checks</h3>
          <p className="m-0">
            Compass sends your goal and selected session messages and evidence through the Claude
            Code or Codex sign-in on this computer. The session’s What is sent section shows the
            exact scope.
          </p>
          {destinations.length ? (
            <p className="m-0">
              Published destinations: <span data-authored>{destinations.join(', ')}</span>.
            </p>
          ) : (
            <p className="m-0">The progress check destination is unavailable.</p>
          )}
          <p className="m-0">
            {promptBytes === null
              ? 'The saved prompt size limit is unavailable.'
              : `Saved prompt size limit: ${kilobytes(promptBytes)}.`}
          </p>
        </div>
        <div>
          <h3 className="m-0 text-body font-semibold text-foreground">Summaries</h3>
          {summary?.disclosure ? (
            <p className="m-0" data-authored>
              {summary.disclosure}
            </p>
          ) : (
            <p className="m-0">Summary details are unavailable.</p>
          )}
        </div>
      </div>
    </Disclosure>
  );
}

export function AiUseSettings({ promptBytes }: { readonly promptBytes: number | null }) {
  return (
    <Card as="section" aria-labelledby="settings-ai-use" className="mt-4 p-0">
      <div className="px-4 pt-4 sm:px-6">
        <h2 id="settings-ai-use" className="m-0 text-value font-bold">
          {GLOSSARY.aiUse.plain}
        </h2>
        <p className="mb-0 text-body text-muted-foreground">
          Progress checks use your Claude Code or Codex sign-in. Session summaries use Claude Code.
        </p>
      </div>
      <div className="p-4 sm:px-6">
        <AiPauseSwitch>{(paused) => <SummariesSwitch paused={paused} />}</AiPauseSwitch>
      </div>
      <p className="m-0 [border-block-start:1px_solid_var(--rule)] px-4 py-3 text-body text-muted-foreground sm:px-6">
        <strong className="text-foreground">{GLOSSARY.liveMonitor.plain}:</strong> Turn it on in a
        session’s technical details. It checks progress about once a minute while you watch.
      </p>
      <div className="[border-block-start:1px_solid_var(--rule)] px-4 sm:px-6">
        <WhatIsSent promptBytes={promptBytes} />
      </div>
    </Card>
  );
}
