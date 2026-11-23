import { useId, useState } from 'react';
import { readingOff, readingOn } from '../drift/actions';
import { currentPayload, overlaid } from '../drift/overlay';
import { readingsOff, readingsOn } from '../drift/route';
import { driftCtxFor, useDriftVersion } from '../drift/state';
import { GLOSSARY } from '../language/glossary';
import { isRecord, type Row } from '../observed';
import { useDisplayed, useShell } from '../shell/context';
import { Switch } from '../ui/switch';
import type { ReactNode } from 'react';

function modelPause(payload: Row): boolean | null {
  if (readingsOff(payload)) return true;
  if (readingsOn(payload)) return false;

  // Summaries publishes the master pause reason even when annotations are off.
  const summary = payload['summaries'];
  if (!isRecord(summary)) return null;
  if (summary['reason'] === 'model-calls-paused') return true;
  if (summary['reason'] === 'summaries-off' || summary['reason'] === 'daily-cap') return false;
  return summary['consent'] === true ? false : null;
}

export function AiPauseSwitch({
  children,
}: {
  readonly children?: (paused: boolean | null) => ReactNode;
}) {
  const shell = useShell();
  const ctx = driftCtxFor(shell);
  useDriftVersion(ctx.drift);
  const board = useDisplayed((snapshot) => snapshot);
  const payload = board.data
    ? overlaid(board.data as unknown as Row, ctx.drift.getOverlay(), board.acceptedCount)
    : null;
  const fresh =
    !board.failures ||
    Boolean(ctx.drift.getOverlay().reading && ctx.drift.getOverlay().stamp === board.acceptedCount);
  const paused = payload && fresh ? modelPause(payload) : null;
  const [failure, setFailure] = useState('');
  const id = useId();
  const label = paused ? GLOSSARY.resumeAi.plain : GLOSSARY.pauseAi.plain;
  const pending = board.pending.some(
    (key) => key === 'reading-on' || key === 'reading-off' || /^reading-(off|on):/.test(key),
  );

  if (paused === null) {
    return (
      <div className="flex flex-col items-start gap-1">
        <p className="m-0 text-label text-muted-foreground">
          {!fresh
            ? 'Compass could not refresh the AI pause setting.'
            : 'The AI pause setting is unavailable.'}
        </p>
        {children?.(null)}
      </div>
    );
  }
  return (
    <div className="flex w-full flex-col gap-2">
      <div className="flex items-center justify-between gap-3">
        <div>
          <p id={`${id}-label`} className="m-0 text-body font-semibold">
            {label}
          </p>
          <p id={id} className="m-0 text-label text-muted-foreground">
            Applies to every session.
          </p>
        </div>
        <Switch
          aria-labelledby={`${id}-label`}
          aria-describedby={id}
          aria-disabled={pending || undefined}
          aria-busy={pending || undefined}
          readOnly={pending}
          checked={paused}
          onCheckedChange={async (next) => {
            const current = currentPayload(ctx);
            const currentPause = current ? modelPause(current) : null;
            if (currentPause === null || currentPause === next) return;
            setFailure('');
            const saved = await (next ? readingOff : readingOn)(ctx, null);
            if (!saved)
              setFailure(
                next ? 'Could not confirm AI use is paused.' : 'Could not confirm AI use resumed.',
              );
          }}
        />
      </div>
      {failure ? <p role="status">{failure}</p> : null}
      {children?.(paused)}
    </div>
  );
}
