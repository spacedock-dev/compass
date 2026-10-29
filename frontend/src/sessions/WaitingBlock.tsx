import { Card } from '../ui/card';
import type { ObservedSession } from '../observed';
import { RouteLink } from '../shell/RouteLink';

export const WAITING_ANSWER_WHERE =
  "Answer it in the session's own terminal. Compass cannot answer a harness's own prompt.";

/* A harness's own gate (a permission prompt, a question or a plan approval the harness asks itself) has no
   exact request Compass can show or answer, so the Asked-you block never draws for it. Before this the
   pill was the page's only sign of the wait (owner, 2026-10-29): this says it is waiting, for how long,
   what the harness said of it, and where it is answered. The raise stays in the header's controls; the
   resume command stays off this page (docs/design-reading-a-session.md, "The resume command after the
   Copy buttons go"), so the block points to Attention for it. */
export function WaitingBlock({ observed }: { readonly observed: ObservedSession }) {
  return (
    <Card
      as="section"
      variant="session-ask"
      className="next-session-section my-5"
      aria-label="Waiting on you"
      data-next-session-section="waiting"
    >
      <div className="next-session-ask-callout">
        <span>
          {'WAITING ON YOU · '}
          <span className="next-session-wait" data-known={String(observed.waitedKnown === true)}>
            {observed.waitedText}
          </span>
        </span>
      </div>
      <p className="next-session-ask-question mt-[10px] mb-[6px]" data-next-session-wait-note>
        {observed.blockNote}
      </p>
      <p className="m-0 text-muted-foreground text-body">
        {`${WAITING_ANSWER_WHERE} The command back into it is on `}
        <RouteLink route={{ view: 'attention' }}>Attention</RouteLink>.
      </p>
    </Card>
  );
}
