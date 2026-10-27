/* The page's icons: Phosphor, through react-icons, and nothing else. One family keeps stroke, corner and
   optical weight consistent, and Phosphor's weights let one glyph say two things in one hand: a hollow
   circle is "ran, nothing recorded", the same circle with a mark is a recorded result. Every icon the page
   draws is named here, so a second set cannot enter a component by habit. Each is decorative by default
   (`aria-hidden`): the words that mean the same thing sit beside it, or on its trigger as a name.
   docs/design-shadcn-adoption.md#icons-and-tooltips owns the choice and what it was weighed against. */
import type { IconBaseProps } from 'react-icons';
import {
  PiCaretRight,
  PiCheckCircle,
  PiCircle,
  PiClockCounterClockwise,
  PiCompass,
  PiCopy,
  PiInfo,
  PiListChecks,
  PiTerminal,
  PiWarning,
  PiX,
  PiXCircle,
} from 'react-icons/pi';

export type IconName =
  | 'unrecorded'
  | 'passed'
  | 'command'
  | 'failed'
  | 'stale'
  | 'earlier-failed'
  | 'checks'
  | 'info'
  | 'expand'
  | 'remove'
  | 'compass'
  | 'copy';

const ICONS = {
  unrecorded: PiCircle,
  passed: PiCheckCircle,
  command: PiTerminal,
  failed: PiXCircle,
  stale: PiClockCounterClockwise,
  'earlier-failed': PiWarning,
  checks: PiListChecks,
  info: PiInfo,
  expand: PiCaretRight,
  remove: PiX,
  compass: PiCompass,
  copy: PiCopy,
} as const;

export function Icon({ name, ...props }: { readonly name: IconName } & IconBaseProps) {
  const Glyph = ICONS[name];
  return (
    <Glyph
      data-icon={name}
      aria-hidden="true"
      focusable="false"
      size="1.1em"
      className="shrink-0"
      {...props}
    />
  );
}
