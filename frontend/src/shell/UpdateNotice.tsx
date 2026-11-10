import { useReducer } from 'react';
import type { PayloadData } from '../api/types';
import type { LegacyStorage } from '../storage';
import { useFocusKey } from '../controls/useFocusKey';
import type { FocusLane } from '../controls/focusLane';
import { Alert } from '../ui/alert';
import { Button } from '../ui/button';

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
    <Alert variant="intent-note" className="flex flex-wrap items-center gap-3">
      <span>{`Compass ${version} is available`}</span>
      <a
        href="https://github.com/spacedock-dev/compass/releases/latest"
        target="_blank"
        rel="noreferrer"
      >
        View release
      </a>
      <Button
        ref={dismissRef}
        type="button"
        variant="quiet"
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
