import { Button } from '../ui/button';
import { contextKey } from '../api/identity';
import type { SessionIdentity } from '../api/types';
import { Disclosure } from './Disclosure';
import { disclosureKey } from './disclosureStore';
import { useControls, useKeyedValue } from './kit';
import { BriefingUnavailable } from './briefingUnavailable';

export interface MoreMenuProps {
  /** The stable project key, never a label assumed unique. */
  readonly projectKey: string;
  /** The exact focused session, or null at project scope. */
  readonly focus: SessionIdentity | null;
  readonly running: number;
  readonly subagents: number;
  /** Read only inside the press that copies it: the briefing is never built, let alone sent, on a render. */
  readonly briefingText: () => string;
  /** Present only while the note is empty and the briefing complete, so the utility is offered where it adds something. */
  readonly addHumanContext?: { readonly memoKey: string };
}

const MORE_KEY = disclosureKey({ project: null, scope: null, name: 'more' });

/* Project-only: the caller draws it on a project route and nowhere else. It
   keeps the all-project status the project page would otherwise hide, which is
   why it is not just a Copy button.

   Copy briefing's result is held with no expiry and keyed by the project and
   session context, so the control keeps reading Copied or Copy unavailable until
   the scope changes. Unlike the two confirmation cues, nothing deletes it: the
   briefing is a snapshot the reader chose to take, and an expired "Copied" would
   invite a second press to learn what the first did. */
export function MoreMenu({
  projectKey,
  focus,
  running,
  subagents,
  briefingText,
  addHumanContext,
}: MoreMenuProps) {
  const controls = useControls();
  const key = contextKey(projectKey, focus);
  const state = useKeyedValue(controls.briefing, key);
  const label =
    state === 'copied' ? 'Copied' : state === 'error' ? 'Copy unavailable' : 'Copy briefing';

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
    <Disclosure
      disclosureKey={MORE_KEY}
      variant="menu"
      summary="More"
      summaryLabel="More"
      focusKey="more"
    >
      <div className="ctl-menu-items">
        <span className="ctl-menu-status">
          {`All projects · ${String(running)} running · ${String(subagents)} ${subagents === 1 ? 'subagent' : 'subagents'} observed`}
        </span>
        <Button variant="menu" type="button" onClick={() => void copy()}>
          {label}
        </Button>
        {addHumanContext ? (
          <Button
            variant="menu"
            type="button"
            onClick={() => controls.startMemoEdit(addHumanContext.memoKey)}
          >
            Add human context
          </Button>
        ) : null}
      </div>
    </Disclosure>
  );
}
