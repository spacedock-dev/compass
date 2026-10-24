import { useEffect, useRef, type ReactNode, type SyntheticEvent } from 'react';
import { heldControl, isHeld } from './held';

/* The sample is view only. Nothing it can send reaches a server (`sampleFetch` refuses every write), and
   this stops the press itself, so a reader sees one sentence about why rather than an error from a request
   that was never going to work. Reading controls stay live: links, disclosures, the select, the numbered
   marks, the cited entry numbers and Back to the finding, Steer back and Copy, which only composes and
   copies words. Everything else that edits, saves, turns readings on or off, or runs is held. */
export function ViewOnly({
  children,
  onHeld,
}: {
  readonly children: ReactNode;
  /** The control whose press was held, so the sentence is drawn beside it. */
  readonly onHeld: (control: Element) => void;
}) {
  const root = useRef<HTMLDivElement>(null);
  const hold = (event: Event | SyntheticEvent) => {
    const target = event.target instanceof Element ? event.target : null;
    if (!target || !isHeld(target)) return;
    event.preventDefault();
    event.stopPropagation();
    onHeld(heldControl(target));
  };
  /* The browser's own `beforeinput`, which is what typing, pasting and deleting raise. React's `onBeforeInput`
     is a different, older event, so typing is held here, on the node, in the capture phase. */
  useEffect(() => {
    const node = root.current;
    if (!node) return undefined;
    const listener = (event: Event) => hold(event);
    node.addEventListener('beforeinput', listener, true);
    return () => node.removeEventListener('beforeinput', listener, true);
  });
  return (
    <div
      ref={root}
      data-sample-view-only
      onClickCapture={hold}
      onSubmitCapture={hold}
      onDropCapture={hold}
      onPasteCapture={hold}
      onKeyDownCapture={(event) => {
        // Enter or Space on a held button is the same press as a click.
        if (event.key === 'Enter' || event.key === ' ') hold(event);
      }}
    >
      {children}
    </div>
  );
}
