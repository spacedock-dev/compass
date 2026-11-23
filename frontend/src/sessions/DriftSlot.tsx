import type { ReactNode } from 'react';
import { IntentPanel } from '../intent/IntentPanel';
import type { Row } from '../observed';

export function DriftSlot({
  session,
  payload,
  project,
  drift,
  actions,
  children,
}: {
  readonly session: Row;
  readonly payload: Row;
  readonly project: string;
  readonly drift?: ReactNode;
  readonly actions?: ReactNode;
  readonly children?: ReactNode;
}) {
  return (
    <IntentPanel
      // Keyed by the exact pair so a move to another session builds new editors: a node reused across sessions
      // carries the native undo stack with it, and one undo in session B brought session A's words into B's box.
      key={`${String(session['harness'] ?? '')}\u0000${String(session['sid'] ?? '')}`}
      session={session}
      payload={payload}
      project={project}
      {...(drift ? { drift } : {})}
      {...(actions ? { actions } : {})}
    >
      {children}
    </IntentPanel>
  );
}
