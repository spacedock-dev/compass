import { useEffect, useState } from 'react';
import type { SettingsBody } from '../api/types';
import { LongHistoryControl } from '../drift/LongHistoryControl';
import { LongPlanControl } from '../drift/LongPlanControl';
import { ReadingAllowance } from '../drift/ReadingAllowance';
import { useDrift } from '../drift/context';
import { isSampleSession } from '../intent/liveMonitor';
import { useRunBoard } from '../drift/useRunBoard';
import { fieldsOf, formatAmount, settingsBody, withUnit } from '../settings/model';
import { RouteAnchor } from './RouteAnchor';

function CheckLimits({ visible }: { readonly visible: boolean }) {
  const { ctx } = useDrift();
  const client = ctx.shell.runtime.client;
  const [limits, setLimits] = useState<SettingsBody | null>(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    if (!visible) return;
    const controller = new AbortController();
    void client.getSettings({ signal: controller.signal }).then((answer) => {
      if (controller.signal.aborted) return;
      const body = answer.kind === 'ok' ? settingsBody(answer.body) : null;
      setLimits(body);
      setFailed(!body);
    });
    return () => controller.abort();
  }, [client, visible]);
  if (!limits)
    return (
      <p className="m-0 text-label text-muted-foreground">
        {failed ? 'The check settings could not be read.' : 'Reading the settings in force.'}
      </p>
    );
  return (
    <dl className="m-0 flex flex-col gap-2">
      {fieldsOf(limits).map((field) => (
        <div key={field.key} className="flex flex-wrap justify-between gap-x-3">
          <dt>{field.key === 'analyze_prompt_bytes' ? 'Prompt size limit' : field.label}</dt>
          <dd className="m-0 font-semibold">
            {field.key === 'analyze_prompt_bytes'
              ? `${withUnit(field, field.value)} of ${withUnit(field, field.maximum)} allowed (${formatAmount(field.value * field.scale)} bytes)`
              : field.key === 'analyze_scan_megabytes'
                ? withUnit(field, field.value)
                : formatAmount(field.value)}
          </dd>
        </div>
      ))}
    </dl>
  );
}

export function SessionCheckSettings({ visible }: { readonly visible: boolean }) {
  const { model } = useDrift();
  const { board } = useRunBoard();
  const sample = isSampleSession(model.session);
  return (
    <div className="flex max-w-[var(--measure)] flex-col gap-3 pt-3">
      <div>
        <h2 className="m-0 text-value font-semibold">Check settings</h2>
        <p className="m-0 text-label text-muted-foreground">
          {sample ? (
            'Live check settings are unavailable in this view-only sample.'
          ) : (
            <>
              How much of the session a progress check reads. Change these limits in{' '}
              <RouteAnchor route={{ view: 'settings', project: null, session: null }}>
                Settings
              </RouteAnchor>
              .
            </>
          )}
        </p>
      </div>
      {sample ? null : <CheckLimits visible={visible} />}
      <ReadingAllowance route={model.route} />
      <LongPlanControl key={`long:${model.key}`} board={board} />
      <LongHistoryControl key={`long-history:${model.key}`} />
    </div>
  );
}
