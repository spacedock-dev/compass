import { Card } from '../ui/card';
import { resumeCommand } from '../controls';
import { SHOWN } from '../language/glossary';
import { SESSION_TEXT_ORIGIN, type ObservedSession } from '../observed';
import { RouteLink } from '../shell/RouteLink';

export const WAITING_ANSWER_WHERE =
  "Answer it where the session is running. Compass cannot answer a harness's own prompt.";

/* A harness's own gate (a permission prompt, a question or a plan approval the harness asks itself) has no
   exact request Compass can show or answer, so the Asked-you block never draws for it. Before this the
   pill was the page's only sign of the wait (owner, 2026-10-29): this says it is waiting, for how long,
   what the harness said of it, and where it is answered. The raise stays in the header's controls; the
   resume command lives on Needs you (docs/design-reading-a-session.md, "The resume command after the
   Copy buttons go"). */
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
          {'Waiting on you · '}
          <span className="next-session-wait" data-known={String(observed.waitedKnown === true)}>
            {observed.waitedText}
          </span>
        </span>
      </div>
      <p
        className="next-session-ask-question mt-[10px] mb-[6px]"
        data-next-session-wait-note
        data-authored={observed[SESSION_TEXT_ORIGIN].blockNote || undefined}
      >
        {observed.blockNote}
      </p>
      <p className="m-0 text-muted-foreground text-body">
        {WAITING_ANSWER_WHERE}
        {/* The command needs a session id the harness's CLI accepts (Claude Code, Codex). */}
        {resumeCommand(observed.harness, String(observed.resume_id || '')) ? (
          <>
            {' The command back into it is on '}
            <RouteLink route={{ view: 'attention' }}>{SHOWN.attention}</RouteLink>.
          </>
        ) : null}
      </p>
    </Card>
  );
}
