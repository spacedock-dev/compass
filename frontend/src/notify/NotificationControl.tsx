import { useSyncExternalStore } from 'react';
import { useFocusKey } from '../controls/useFocusKey';
import { SettingsRow } from '../settings/SettingsRow';
import { useDisplayed, useShell } from '../shell/context';
import { Button } from '../ui/button';
import { notifyOwnerFor } from './registry';

const WORDS: Readonly<Record<string, string>> = {
  granted: 'Allowed in this browser.',
  denied:
    'Blocked in this browser. To allow notifications, change this site’s permissions in your browser.',
  unsupported: 'This browser does not support desktop notifications.',
  default: 'No notification permission decision yet.',
};

export function NotificationControl() {
  const { runtime, controls } = useShell();
  const owner = notifyOwnerFor(runtime);
  useSyncExternalStore(owner.subscribe, owner.version);
  const board = useDisplayed((snapshot) => snapshot);
  const native = Boolean(board.data?.['native_notify']);
  const browserOwns = Boolean(board.data) && !board.failures && !native;
  const stateRef = useFocusKey<HTMLParagraphElement>(controls.focusLane, 'notify-permission');
  const buttonRef = useFocusKey<HTMLButtonElement>(controls.focusLane, 'notify-enable', {
    fallback: 'notify-permission',
  });
  const permission = owner.permission();
  const pending = owner.requesting();
  const message = board.failures
    ? 'Compass could not refresh the desktop notification setting.'
    : !board.data
      ? 'Reading the desktop notification setting.'
      : native
        ? 'Compass sends desktop notifications directly on this computer.'
        : pending
          ? 'Waiting for your browser’s permission.'
          : (WORDS[permission] ?? 'The browser did not report its notification permission.');
  return (
    <SettingsRow
      title="Desktop notifications"
      description={
        <>
          <p className="m-0">Show a desktop notification when a session is waiting on you.</p>
          <p ref={stateRef} tabIndex={-1} role="status" className="m-0">
            {message}
          </p>
        </>
      }
    >
      {browserOwns && permission === 'default' ? (
        <Button
          ref={buttonRef}
          type="button"
          aria-busy={pending || undefined}
          aria-disabled={pending || undefined}
          onClick={() => owner.request()}
        >
          Allow
        </Button>
      ) : null}
    </SettingsRow>
  );
}
