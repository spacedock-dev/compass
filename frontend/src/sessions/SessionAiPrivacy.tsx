import { progressBudget } from '../drift/route';
import { CiReadSettingNote } from '../drift/CiReadNote';
import { WhatIsSent } from '../drift/ReadingControl';
import { useDrift } from '../drift/context';
import { LiveMonitorSwitch } from '../intent/LiveMonitorSwitch';
import { isSampleSession } from '../intent/liveMonitor';
import { GLOSSARY } from '../language/glossary';
import { AiPauseSwitch } from '../settings/AiPauseSwitch';
import { Separator } from '../ui/separator';

export function SessionAiPrivacy() {
  const { model } = useDrift();
  const route = model.route;
  const budget = progressBudget(model.payload);
  const sample = isSampleSession(model.session);
  const facts = [
    [
      'Sent to',
      [route?.['words_destination'] || route?.['destination'], route?.['label']]
        .filter(Boolean)
        .join(' · '),
    ],
    ['Model', String(route?.['model'] ?? '')],
    [
      'Checks left today',
      budget
        ? `${budget.remaining} of ${budget.limit} daily checks`
        : 'Daily check count unavailable.',
    ],
  ].filter(([, value]) => value);
  return (
    <div className="flex max-w-[var(--measure)] flex-col gap-3 pt-3">
      <div>
        <h2 className="m-0 text-value font-semibold">{GLOSSARY.aiUseAndPrivacy.plain}</h2>
        {route?.['provider'] ? (
          <p className="m-0 text-label text-muted-foreground">
            Compass uses the command-line sign-in on this machine for progress checks.
          </p>
        ) : null}
      </div>
      {facts.length ? (
        <dl className="m-0 flex flex-col gap-2">
          {facts.map(([label, value]) => (
            <div key={label} className="flex flex-wrap justify-between gap-x-3">
              <dt>{label}</dt>
              <dd className="m-0 font-semibold">{value}</dd>
            </div>
          ))}
        </dl>
      ) : null}
      <WhatIsSent technical />
      <Separator />
      <LiveMonitorSwitch />
      <div className="flex flex-wrap items-start gap-x-4 gap-y-3">
        {sample ? null : <AiPauseSwitch />}
        <CiReadSettingNote technical />
      </div>
    </div>
  );
}
