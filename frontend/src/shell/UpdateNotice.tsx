import { useReducer } from 'react';
import type { PayloadData } from '../api/types';
import type { LegacyStorage } from '../storage';
import { useFocusKey } from '../controls/useFocusKey';
import type { FocusLane } from '../controls/focusLane';
import { Alert } from '../ui/alert';
import { cn } from '../lib/utils';
import { Button, buttonVariants } from '../ui/button';

export function UpdateNotice({
  update,
  storage,
  focusLane = null,
}: {
  readonly update: PayloadData['update_check'];
  readonly storage: LegacyStorage;
  readonly focusLane?: FocusLane | null;
}) {
  const [, redraw] = useReducer((value: number) => value + 1, 0);
  const dismissRef = useFocusKey<HTMLButtonElement>(focusLane, 'dismiss-update', {
    fallback: 'primary-current',
  });
  const version = update?.version;
  if (!version || storage.updateDismissals.dismissed(version)) return null;
  return (
    <Alert
      aria-label="Compass update"
      variant="notice"
      className="mt-4 flex flex-wrap items-center gap-x-4 gap-y-2 py-2"
    >
      <strong>{`Compass ${version} is available`}</strong>
      <a
        className={cn(
          buttonVariants({ variant: 'native' }),
          'inline-flex items-center text-[color:var(--accent-dim)] underline',
        )}
        href="https://github.com/spacedock-dev/compass/releases/latest"
        target="_blank"
        rel="noreferrer"
      >
        View release
      </a>
      <Button
        ref={dismissRef}
        type="button"
        emphasis="quiet"
        className="ml-auto text-[color:var(--accent-dim)]"
        aria-label="Dismiss update notice"
        onClick={() => {
          storage.updateDismissals.dismiss(version);
          redraw();
        }}
      >
        Dismiss
      </Button>
    </Alert>
  );
}
