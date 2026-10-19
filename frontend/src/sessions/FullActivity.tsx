import type { ReactNode } from 'react';
import { compatSessKey } from '../api/identity';
import { useControls, useFocusKey } from '../controls';
import { useControlledDisclosureState } from '../controls/useDisclosureState';
import { useRevealFragment } from '../controls/useRevealFragment';
import type { Row } from '../observed';
import { SampleMark } from '../sample/SampleMark';
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '../ui/collapsible';
import { fullActivityKey } from './fullActivityKey';

/* The numbered record and everything about the session that is not its intent, its summary or its drift,
   collapsed under one heading at the foot of the page. A Collapsible rather than the shared Disclosure so the
   sample's numbered mark can sit beside the trigger instead of inside it: a button in a button is not a
   control. The panel stays mounted while closed, so the record still opens and refreshes, and a citation can
   find an entry before the reader has opened the section. */
export function FullActivity({
  project,
  session,
  children,
}: {
  readonly project: string;
  readonly session: Row;
  readonly children: ReactNode;
}) {
  const controls = useControls();
  const key = fullActivityKey(project, session);
  const open = useControlledDisclosureState(controls.disclosures, key);
  const panelRef = useRevealFragment(key);
  const triggerRef = useFocusKey<HTMLButtonElement>(
    controls.focusLane,
    `full-activity:${compatSessKey(session)}`,
  );
  return (
    <section
      className="next-session-activity"
      aria-labelledby="next-session-full-activity-heading"
      data-next-session-activity
      data-next-session-full-activity
    >
      <Collapsible
        className="ctl-disclosure"
        open={open}
        onOpenChange={(next, detail) => {
          if (detail.reason === 'trigger-press') controls.noteToggle();
          controls.disclosures.set(key, next);
        }}
      >
        <div className="flex flex-wrap items-center gap-x-2">
          <h2
            id="next-session-full-activity-heading"
            className="next-session-activity-heading m-0"
            data-next-full-activity-heading
          >
            <CollapsibleTrigger ref={triggerRef} data-next-full-activity-trigger>
              Full activity
            </CollapsibleTrigger>
          </h2>
          <SampleMark id="activity" />
        </div>
        <CollapsibleContent
          ref={panelRef}
          hiddenUntilFound
          className="flex flex-col"
          data-next-full-activity-body
        >
          {children}
        </CollapsibleContent>
      </Collapsible>
    </section>
  );
}
