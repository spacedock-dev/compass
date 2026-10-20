/* Which controls a view-only sample holds. */
const LIVE_ACTIONS = new Set([
  'finding-jump',
  'steer-back',
  'correction-copy',
  'correction-recompose',
  'live-monitor',
  'tab',
]);
/* A trigger that only opens or closes a panel is live; what is inside the panel is judged like any other
   control, so "Clear" in the Intent popover is held. Whole popovers and disclosures were once exempt, and
   that let a press on Clear empty the sample's goal. */
/* Back to the finding only moves focus back to the cited entry a reader pressed, so it is as live as that press. */
const LIVE_REGIONS =
  '[data-sample-tour], [data-next-jump-back], a[href], [data-slot="popover-trigger"], [data-slot="accordion-trigger"], [data-slot="collapsible-trigger"], [role="combobox"], [role="listbox"], [role="option"]';
const CONTROL =
  'button, input, textarea, select, [role="button"], [role="switch"], [role="checkbox"]';

export function isHeld(target: Element): boolean {
  if (target.closest(LIVE_REGIONS)) return false;
  const control = target.closest(CONTROL);
  if (!control) return false;
  const action = control
    .closest('[data-next-cockpit-action]')
    ?.getAttribute('data-next-cockpit-action');
  return !(action && LIVE_ACTIONS.has(action));
}

/* The control a held press landed on, or the target itself. */
export function heldControl(target: Element): Element {
  return target.closest(CONTROL) ?? target;
}

export type HeldAt =
  | { readonly top: number; readonly left: number }
  | { readonly bottom: number; readonly left: number };

/* Under the control, its left edge kept inside the box so the sentence never runs off a narrow screen. A
   control too near the viewport's foot gets the sentence above it instead: drawn below, it would be off
   screen and lapse unseen. The room asked for is the sentence at its narrowest, wrapped onto three lines. */
const HELD_WIDTH = 448;
const HELD_ROOM = 80;
export function heldPosition(control: DOMRect, box: DOMRect, viewport = Infinity): HeldAt {
  const width = Math.min(HELD_WIDTH, box.width - 16);
  const left = Math.max(8, Math.min(control.left - box.left, box.width - width - 8));
  if (control.bottom + 6 + HELD_ROOM > viewport && control.top - 6 - HELD_ROOM >= 0) {
    return { bottom: box.bottom - control.top + 6, left };
  }
  return { top: control.bottom - box.top + 6, left };
}
