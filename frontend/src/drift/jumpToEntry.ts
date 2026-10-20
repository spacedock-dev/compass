import { afterPanelSettles } from './panelSettle';
import type { DriftValue } from './context';
import { fullActivityKey } from '../sessions/fullActivityKey';

const LAND_SETTLE_MS = 1500;

/* Places a numbered entry of Full activity in view and focuses it, or says it is not drawn. */
export function landOnEntry(id: string): boolean {
  const node = document.querySelector<HTMLElement>(
    `[data-next-cockpit-work] [data-next-entry-id="${CSS.escape(id)}"]`,
  );
  if (!node) return false;
  node.focus({ preventScroll: true });
  const reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  node.scrollIntoView({ behavior: reduce ? 'instant' : 'smooth', block: 'center' });
  if (!reduce) {
    /* A smooth scroll runs against the page as it was when it started. Full activity opening or its rows
       arriving under it moved the row after that, and the scroll ended with the row at the foot of the
       screen or below it, so it is checked once where the scroll ends and placed again if it is off screen.
       The check is dropped after a moment, so a scroll of the reader's own is never answered. */
    const recheck = () => {
      window.clearTimeout(drop);
      const box = node.getBoundingClientRect();
      if (box.top < 0 || box.bottom > window.innerHeight)
        node.scrollIntoView({ behavior: 'instant', block: 'center' });
    };
    const drop = window.setTimeout(
      () => window.removeEventListener('scrollend', recheck),
      LAND_SETTLE_MS,
    );
    window.addEventListener('scrollend', recheck, { once: true });
  }
  return true;
}

/* A press on an entry the page already holds: Full activity opens, and the row is placed once its panel has
   finished easing open, as a citation in the summary does. */
export function jumpToEntry(drift: DriftValue, id: string): void {
  const { ctx, model } = drift;
  ctx.shell.controls.disclosures.set(fullActivityKey(model.project, model.session), true);
  requestAnimationFrame(() => {
    const panel = document.querySelector('[data-next-full-activity-body]');
    const growing = panel?.getAnimations?.() ?? [];
    void Promise.allSettled(growing.map((animation) => animation.finished)).then(() => {
      afterPanelSettles(() => {
        landOnEntry(id);
      });
    });
  });
}
