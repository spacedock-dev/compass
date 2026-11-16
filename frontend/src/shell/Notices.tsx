import { Alert } from '../ui/alert';
import { Button } from '../ui/button';
import { Disclosure } from '../controls/Disclosure';
import { disclosureKey } from '../controls/disclosureStore';
import { useControls } from '../controls/kit';
import { useFocusKey } from '../controls/useFocusKey';
import type { BoardSnapshot } from '../store/board';
import { selectBuildState } from '../store/selectors';
import { historyResetReason, type HistoryResetReason } from './derive';
import { formatDuration } from './format';

/* A failed refresh is told at the SECOND consecutive failure, never the first. One failed read is
   ordinary (a restart, a sleeping laptop); two in a row is a pattern a reader should be told. The
   store's `selectDataStatus` calls the board stale at one failure, which is the state of the data
   and not a claim worth putting on screen, so this threshold is the legacy one and is held here. */
export const STALLED_AFTER_FAILURES = 2;

const RESET_DETAIL: Readonly<Record<HistoryResetReason, string>> = {
  unreadable: 'The saved file could not be read.',
  version: 'It was written by a different version of Compass.',
};

const BUILD_WHY =
  'Compass was restarted with a different version after this page loaded, and this page may send what that version refuses.';

export interface NoticesProps {
  readonly snapshot: BoardSnapshot;
  /** The clock at draw, for the age of the data on screen. */
  readonly now: number;
  /** The interval the live transport falls back to, which the notice quotes. */
  readonly retryMs: number;
  readonly onRetry: () => void;
  readonly onReload: () => void;
  /** Which route's disclosure the build notice's "Why reload" is. */
  readonly disclosureScope: { readonly project: string | null; readonly scope: string | null };
}

function StalledNotice({
  snapshot,
  now,
  retryMs,
  onRetry,
}: Pick<NoticesProps, 'snapshot' | 'now' | 'retryMs' | 'onRetry'>) {
  const controls = useControls();
  /* `aria-disabled` and never `disabled` while a retry is out: a disabled control gives up focus, and the
     notice's own removal on success would then have no focused node to hand back to the fallback. */
  const retryRef = useFocusKey<HTMLButtonElement>(controls.focusLane, 'retry-refresh', {
    fallback: 'primary-current',
  });
  const failures = snapshot.failures;
  if (failures < STALLED_AFTER_FAILURES) return null;
  const times = failures === STALLED_AFTER_FAILURES ? 'twice' : `${failures} times`;
  let state = 'No data has been received in this tab.';
  if (snapshot.data) {
    const elapsed =
      snapshot.lastSuccessAt === null
        ? null
        : formatDuration(Math.max(0, (now - snapshot.lastSuccessAt) / 1000));
    state = `Displayed data may be stale.${elapsed === null ? '' : ` Last updated ${elapsed} ago.`}`;
  }
  const seconds = Math.max(1, Math.round(retryMs / 1000));
  return (
    <Alert variant="shell-notice" className="next-stalled" data-next-state="stalled" role="status">
      <strong>{`Live refresh failed ${times} in a row.`}</strong>
      <span>{`${state} Retrying automatically every ${seconds}s.`}</span>
      <Button
        variant="retry"
        ref={retryRef}
        type="button"
        data-next-action="retry-refresh"
        aria-disabled={snapshot.manualRefreshing || undefined}
        onClick={snapshot.manualRefreshing ? undefined : onRetry}
      >
        Retry now
      </Button>
    </Alert>
  );
}

/* Which reset it was, not merely that one happened: a corruption reset may be the reader's own disk
   while a version reset is ours, and one message for both would lose the only thing it is there to
   tell them apart by. */
function HistoryResetNotice({ reason }: { readonly reason: HistoryResetReason }) {
  return (
    <Alert
      variant="shell-notice"
      className="next-stalled"
      data-next-state="history-reset"
      role="status"
    >
      <strong>The saved history was reset.</strong>
      <span>{`${RESET_DETAIL[reason]} The rail and the delegation figure start from this tab.`}</span>
    </Alert>
  );
}

/* Tier 1 is the instruction, and why sits behind its disclosure, after the two notices above it,
   which say the data itself may be wrong. */
function BuildNotice({
  onReload,
  disclosureScope,
}: Pick<NoticesProps, 'onReload' | 'disclosureScope'>) {
  return (
    <Alert
      variant="shell-notice"
      className="next-stalled"
      data-next-state="build-changed"
      role="status"
    >
      <strong>Reload to use the new version.</strong>
      <Button type="button" data-next-action="reload-page" onClick={onReload}>
        Reload
      </Button>
      <Disclosure
        disclosureKey={disclosureKey({ ...disclosureScope, name: 'build-changed' })}
        summary="Why reload"
        className="next-why"
      >
        <p className="next-why-body">{BUILD_WHY}</p>
      </Disclosure>
    </Alert>
  );
}

/* Failed refresh, history reset and a newer server build are three distinct notices that do not
   fabricate a fresh success: none of them says the board is current, and each is derived from the
   snapshot rather than authored. */
export function Notices({
  snapshot,
  now,
  retryMs,
  onRetry,
  onReload,
  disclosureScope,
}: NoticesProps) {
  const reset = historyResetReason(snapshot.data);
  return (
    <>
      {snapshot.tunnelPortMismatch ? (
        <Alert
          variant="shell-notice"
          className="next-stalled"
          data-next-state="tunnel-port-mismatch"
          role="status"
        >
          <strong>Action refused.</strong>
          <span>
            {"For an ssh -L tunnel, the local port must match the Compass server's port."}
          </span>
        </Alert>
      ) : null}
      <StalledNotice snapshot={snapshot} now={now} retryMs={retryMs} onRetry={onRetry} />
      {reset ? <HistoryResetNotice reason={reset} /> : null}
      {selectBuildState(snapshot) === 'reload-required' ? (
        <BuildNotice onReload={onReload} disclosureScope={disclosureScope} />
      ) : null}
    </>
  );
}
