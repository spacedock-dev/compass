import { useId } from 'react';
import { parseGrant } from '../api/summary';
import { setSummaries } from '../sessions/summaryActions';
import { grantShown, summaryHeldFor, useSummaryHeld } from '../sessions/summaryHeld';
import { useDisplayed, useShell } from '../shell/context';
import { Switch } from '../ui/switch';
import { AiPauseSwitch } from './AiPauseSwitch';

function SummariesSwitch({ paused }: { readonly paused: boolean }) {
  const shell = useShell();
  const data = useDisplayed((snapshot) => snapshot.data);
  const pending = useDisplayed((snapshot) => snapshot.pending.includes('summary-grant:settings'));
  const held = summaryHeldFor(shell.runtime);
  const note = useSummaryHeld(held, 'settings');
  const grant = grantShown(held, parseGrant(data?.['summaries']), Number(data?.generated ?? 0));
  const id = useId();
  if (!grant) return null;
  if (grant.reason === 'store-unavailable') {
    return (
      <p className="m-0 text-label text-muted-foreground">The Summaries setting is unavailable.</p>
    );
  }
  return (
    <div className="border-s border-[var(--rule)] ps-4">
      <div className="flex items-center gap-2">
        <Switch
          aria-labelledby={`${id}-label`}
          aria-describedby={id}
          aria-disabled={paused || pending || undefined}
          readOnly={paused || pending}
          checked={!paused && !grant.off}
          onCheckedChange={(on) => {
            if (!paused) void setSummaries(shell, null, on);
          }}
        />
        <span id={`${id}-label`} className="text-body font-semibold">
          Summaries
        </span>
      </div>
      <p id={id} className="m-0 text-label text-muted-foreground">
        {paused ? 'Paused while AI use is paused.' : 'Applies to session summaries.'}
      </p>
      {note.failed ? <p role="status">{note.failed}</p> : null}
    </div>
  );
}

export function AiUseSettings() {
  return (
    <div className="mt-4 flex flex-col items-start gap-3">
      <AiPauseSwitch>{(paused) => <SummariesSwitch paused={paused} />}</AiPauseSwitch>
      <p className="m-0 text-label text-muted-foreground">
        Live monitor is in AI use and privacy under Show technical details on the session page.
      </p>
    </div>
  );
}
