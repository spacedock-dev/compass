import { useEffect } from 'react';
import { useAnnouncer } from '../shell/announcerContext';
import type { Announcer } from '../shell/announcer';
import { useDisplayed } from '../shell/context';
import { selectAttentionSelection, type AttentionSelection } from './select';

/* The previous model each announcer has spoken against. Held outside the component so a remount (a hot
   update, StrictMode's second effect) compares against what was last heard rather than against nothing,
   which would announce the whole board again. */
const previous = new WeakMap<Announcer, AttentionSelection['counts']>();

/* "Needs you updated: ..." in the polite status region when a queue changes length, on any page. The
   first board announces nothing: arriving is not a change. Reads the DISPLAYED model, so a poll held back
   by an open option list is announced when it is shown, not while the reader still sees the old one. */
export function AttentionAnnouncer() {
  const announcer = useAnnouncer();
  const selection = useDisplayed(selectAttentionSelection);
  const counts = selection?.counts ?? null;
  useEffect(() => {
    const before = previous.get(announcer);
    previous.set(announcer, counts);
    if (!before || !counts) return;
    const { waitingOnYou, worthALook, readyToWrapUp } = counts;
    if (
      before.waitingOnYou === waitingOnYou &&
      before.worthALook === worthALook &&
      before.readyToWrapUp === readyToWrapUp
    )
      return;
    announcer.say(
      'attention',
      `Needs you updated: ${waitingOnYou} waiting on you, ${worthALook} worth a look, ${readyToWrapUp} ready to wrap up.`,
    );
  }, [announcer, counts]);
  return null;
}
