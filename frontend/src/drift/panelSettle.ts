/* Runs `then` once Full activity's panel has finished easing open. While it eases its height is a measured pixel
   value under `overflow: clip`, so a scroll begun then is clamped at the foot of a page not yet tall enough. The
   row's visually hidden source line once hid that: absolutely placed, it escaped the clip and stretched the
   page, and taking the line out of every row exposed the clamp. Base UI publishes `auto` once the panel rests. A
   panel that never reports its end is waited on for at most `SETTLE_MS`. */
const SETTLE_MS = 400;

export function afterPanelSettles(then: () => void): void {
  const panel = document.querySelector<HTMLElement>('[data-next-full-activity-body]');
  const height = panel?.style.getPropertyValue('--collapsible-panel-height').trim() ?? 'auto';
  if (!panel || height === '' || height === 'auto') {
    then();
    return;
  }
  let done = false;
  const finish = () => {
    if (done) return;
    done = true;
    panel.removeEventListener('transitionend', onEnd);
    window.clearTimeout(timer);
    // A frame later, so the resting height is written before the row is placed.
    requestAnimationFrame(then);
  };
  const onEnd = (event: TransitionEvent) => {
    if (event.target === panel) finish();
  };
  panel.addEventListener('transitionend', onEnd);
  const timer = window.setTimeout(finish, SETTLE_MS);
}
