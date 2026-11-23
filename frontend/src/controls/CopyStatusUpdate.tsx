import { Button } from '../ui/button';
import { contextKey } from '../api/identity';
import type { SessionIdentity } from '../api/types';
import { useControls, useKeyedValue } from './kit';
import { BriefingUnavailable } from './briefingUnavailable';

export interface CopyStatusUpdateProps {
  /** The stable project key, never a label assumed unique. */
  readonly projectKey: string;
  /** The exact focused session, or null at project scope. */
  readonly focus: SessionIdentity | null;
  /** Read only inside the press that copies it: the briefing is never built, let alone sent, on a render. */
  readonly briefingText: () => string;
}

/* Copy a status update's result is held with no expiry and keyed by the project and
   session context, so the control keeps reading Copied or Copy unavailable until
   the scope changes. Unlike the two confirmation cues, nothing deletes it: the
   briefing is a snapshot the reader chose to take, and an expired "Copied" would
   invite a second press to learn what the first did. */
export function CopyStatusUpdate({ projectKey, focus, briefingText }: CopyStatusUpdateProps) {
  const controls = useControls();
  const key = contextKey(projectKey, focus);
  const state = useKeyedValue(controls.briefing, key);
  const label =
    state === 'copied' ? 'Copied' : state === 'error' ? 'Copy unavailable' : 'Copy a status update';

  const copy = async () => {
    const press = controls.press();
    const announceKey = `briefing:${key}#${String(press)}`;
    try {
      const clipboard = controls.clipboard();
      if (!clipboard) throw new Error('clipboard unavailable');
      await clipboard.writeText(briefingText());
    } catch (error) {
      controls.briefing.remember(key, 'error');
      controls.announce(
        announceKey,
        // A briefing that cannot be built says why in its own words (the project is gone from the board), not the clipboard's.
        error instanceof BriefingUnavailable ? error.message : 'The briefing could not be copied',
      );
      return;
    }
    controls.briefing.remember(key, 'copied');
    controls.announce(announceKey, 'Copied the project briefing');
  };

  return (
    <Button variant="default" type="button" onClick={() => void copy()}>
      {label}
    </Button>
  );
}
