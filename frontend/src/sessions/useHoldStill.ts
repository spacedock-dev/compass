import { useEffect } from 'react';

/* Keeps the control the reader is aiming at where it was. The browser's own scroll anchoring does nothing at the
   top of the page, which is where a reader who just arrived presses, so an outline phase arriving above the Drift
   controls, or a summary leaving, slid the control out from under the pointer and the press missed. The control
   under the pointer (or holding focus) is remembered with its position; when the page changes above it, the
   viewport moves by what the control moved. A reader's own scroll re-measures it, so only layout counts. */
const AIMED_AT = 'button, a[href], summary, input, select, textarea, [role="button"], [tabindex]';
const SLOP_PX = 0.5;

export function useHoldStill(node: HTMLElement | null): void {
  useEffect(() => {
    if (!node) return;
    let held: { readonly el: Element; top: number } | null = null;
    const measure = () => {
      if (held?.el.isConnected) held.top = held.el.getBoundingClientRect().top;
      else held = null;
    };
    const aim = (target: EventTarget | null) => {
      const el = target instanceof Element ? target.closest(AIMED_AT) : null;
      held = el && node.contains(el) ? { el, top: el.getBoundingClientRect().top } : null;
    };
    const onAim = (event: Event) => aim(event.target);
    const settle = () => {
      if (!held) return;
      if (!held.el.isConnected) {
        held = null;
        return;
      }
      const moved = held.el.getBoundingClientRect().top - held.top;
      if (Math.abs(moved) > SLOP_PX) window.scrollBy(0, moved);
      measure();
    };
    node.addEventListener('pointerover', onAim);
    node.addEventListener('pointermove', onAim);
    node.addEventListener('focusin', onAim);
    const release = () => {
      held = null;
    };
    node.addEventListener('pointerleave', release);
    // What a press itself changes is the reader's own doing ("Show 50 older entries" adds rows for them to read
    // from where they are), so a press releases the hold until the pointer or focus aims at something again.
    node.addEventListener('click', release, true);
    window.addEventListener('scroll', measure, { passive: true });
    const mutations = new MutationObserver(settle);
    mutations.observe(node, {
      subtree: true,
      childList: true,
      characterData: true,
      attributes: true,
    });
    const sizes = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(settle);
    sizes?.observe(node);
    return () => {
      node.removeEventListener('pointerover', onAim);
      node.removeEventListener('pointermove', onAim);
      node.removeEventListener('focusin', onAim);
      node.removeEventListener('pointerleave', release);
      node.removeEventListener('click', release, true);
      window.removeEventListener('scroll', measure);
      mutations.disconnect();
      sizes?.disconnect();
    };
  }, [node]);
}
