import { Button } from '../ui/button';
import { Icon, type IconName } from '../ui/icons';
import { useFocusKey } from '../controls';
import { useDisplayed, useShell } from '../shell/context';

/* A control whose press is a request in flight draws busy whatever its resting state says: aria-disabled
   and aria-busy with a spinner over its idle label held as an invisible ghost, so its width and its focus
   stay put, and a redraw mid-request neither hides it nor re-arms it. `aria-disabled` and never `disabled`,
   which would drop keyboard focus from the control just pressed. An inert control stays on the page and
   reachable, and refuses its own press, because an inert control that goes silent reads as a dead one. */

export interface ActionButtonProps {
  /** The runtime's pending key for this control; empty for a control that never sends a request. */
  readonly pendingKey?: string;
  readonly label: string;
  readonly busyLabel?: string;
  /** The busy label of a control far narrower than it, held at rest as a hidden ghost in the same cell. */
  readonly reserve?: string;
  readonly inert?: boolean;
  readonly hidden?: boolean;
  /** What describes the control while it is inert: the sentences saying why. Emitted only then, because
   * `aria-disabled` keeps the control in the tab order and a reader would hear "dimmed" and nothing about why. */
  readonly describedBy?: string;
  /** What always describes the control, as an armed discard's warning does. */
  readonly describes?: string;
  readonly focusKey?: string;
  readonly fallbackKey?: string;
  readonly weight?: 'primary' | 'secondary' | 'quiet' | 'none';
  readonly tone?: 'default' | 'muted';
  readonly strongBorder?: boolean;
  readonly className?: string;
  readonly action?: string;
  readonly arg?: string;
  readonly ariaLabel?: string;
  /** What the control does, for a pointer to rest on; the label stays the accessible name. */
  readonly title?: string;
  /** A glyph drawn in place of the label. The label is then the control's accessible name. */
  readonly icon?: IconName;
  readonly ariaPressed?: boolean;
  readonly onPress: (detail: number) => void;
}

export function ActionButton({
  pendingKey = '',
  label,
  busyLabel = '',
  reserve = '',
  inert = false,
  hidden = false,
  describedBy = '',
  describes = '',
  focusKey,
  fallbackKey,
  weight = 'secondary',
  tone,
  strongBorder,
  className,
  action,
  arg,
  ariaLabel,
  title,
  icon,
  ariaPressed,
  onPress,
}: ActionButtonProps) {
  const { controls } = useShell();
  const busy = useDisplayed(
    (snapshot) => Boolean(pendingKey) && snapshot.pending.includes(pendingKey),
  );
  const ref = useFocusKey<HTMLButtonElement>(
    controls.focusLane,
    focusKey ?? null,
    fallbackKey === undefined ? {} : { fallback: fallbackKey },
  );
  const variant = weight === 'none' ? 'native' : weight === 'secondary' ? 'default' : weight;
  return (
    <Button
      ref={ref}
      type="button"
      variant={variant}
      tone={tone}
      strongBorder={strongBorder}
      busyLabel={busyLabel}
      reserve={reserve}
      {...(className ? { className } : {})}
      {...(focusKey ? { 'data-next-focus': focusKey } : {})}
      {...(action ? { 'data-next-cockpit-action': action } : {})}
      {...(arg !== undefined ? { 'data-arg': arg } : {})}
      {...(reserve ? { 'data-next-reserve': '' } : {})}
      {...(ariaLabel || icon ? { 'aria-label': ariaLabel ?? label } : {})}
      {...(ariaPressed !== undefined ? { 'aria-pressed': ariaPressed } : {})}
      {...(title ? { title } : {})}
      {...(hidden ? { hidden: true } : {})}
      {...(busy
        ? { 'aria-disabled': true, 'aria-busy': true, 'data-next-pending': '' }
        : inert
          ? { 'aria-disabled': true }
          : {})}
      {...(!busy && inert && describedBy ? { 'aria-describedby': describedBy } : {})}
      {...(describes ? { 'aria-describedby': describes } : {})}
      onClick={(event) => {
        event.preventDefault();
        onPress(event.detail);
      }}
    >
      {icon ? <Icon name={icon} /> : label}
    </Button>
  );
}
