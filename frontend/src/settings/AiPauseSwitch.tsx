import { useId, useState } from 'react';
import { readingOff, readingOn } from '../drift/actions';
import { currentPayload } from '../drift/overlay';
import { GLOSSARY } from '../language/glossary';
import { Switch } from '../ui/switch';
import { modelPause, useAiPause } from './useAiPause';
import type { ReactNode } from 'react';

export function AiPauseSwitch({
  children,
}: {
  readonly children?: (paused: boolean | null) => ReactNode;
}) {
  const { ctx, paused, fresh, pending } = useAiPause();
  const [failure, setFailure] = useState('');
  const id = useId();
  const label = paused ? GLOSSARY.resumeAi.plain : GLOSSARY.pauseAi.plain;

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
      {pending || failure ? (
        <p role="status">{pending ? 'Saving the AI pause preference…' : failure}</p>
      ) : null}
      {children?.(paused)}
    </div>
  );
}
