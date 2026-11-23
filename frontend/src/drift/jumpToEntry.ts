import { afterPanelSettles } from './panelSettle';
import type { DriftValue } from './context';
import { entriesHeld } from './citations';

const LAND_SETTLE_MS = 1500;

/* Places a numbered entry of Activity log in view and focuses it, or says it is not drawn. */
function landOnEntry(id: string): boolean {
  const node = document.querySelector<HTMLElement>(
    `[data-next-cockpit-work] [data-next-entry-id="${CSS.escape(id)}"]`,
  );
  if (!node || node.closest('[hidden]')) return false;
  node.focus({ preventScroll: true });
  const reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  node.scrollIntoView({ behavior: reduce ? 'instant' : 'smooth', block: 'center' });
  if (!reduce) {
    /* A smooth scroll runs against the page as it was when it started. Activity log opening or its rows
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

/* A press opens Activity log, reads older pages for an unloaded target, and lands after the panel
   has finished opening. A superseded press has no result for its caller to announce. */
export async function openEntry(drift: DriftValue, id: string): Promise<boolean | null> {
  const { ctx, model } = drift;
  const current = drift.revealEntry(id);
  if (!model.byId.has(id) && model.identity) {
    const scope = { projectKey: model.projectKey, session: model.session, cited: [id] };
    await ctx.shell.runtime.resolveRecord(
      { projectKey: model.projectKey, focus: model.identity },
      (snapshot) => entriesHeld(snapshot, scope),
    );
  }
  if (!current()) return null;
  await new Promise<void>((resolve) => requestAnimationFrame(() => resolve()));
  const panel = document.querySelector(
    '[data-next-session-full-activity] [data-slot="accordion-content"]',
  );
  const growing = panel?.getAnimations?.() ?? [];
  await Promise.allSettled(growing.map((animation) => animation.finished));
  return new Promise<boolean | null>((resolve) => {
    afterPanelSettles(() => resolve(current() ? landOnEntry(id) : null));
  });
}
