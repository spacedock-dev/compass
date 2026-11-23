/* Phosphor Bold keeps status, navigation and activity marks in one weight. A hollow circle says
   "ran, nothing recorded"; the marked circle carries a recorded result. Each icon is decorative
   (`aria-hidden`): the words that mean the same thing sit beside it, or on its trigger as a name.
   docs/design-shadcn-adoption.md#icons-and-tooltips owns the choice and what it was weighed against. */
import { SESSION_ROW_WORDS } from '../language/glossary';
import type { IconBaseProps } from 'react-icons';
import {
  PiArrowCounterClockwiseBold,
  PiArrowDownBold,
  PiArrowRightBold,
  PiCaretDownBold,
  PiCaretLeftBold,
  PiCaretRightBold,
  PiCaretUpBold,
  PiCheckBold,
  PiCheckCircleBold,
  PiCircleBold,
  PiClockBold,
  PiClockCounterClockwiseBold,
  PiCompassBold,
  PiCopyBold,
  PiDiamondBold,
  PiEyeSlashBold,
  PiFunnelBold,
  PiInfoBold,
  PiListBold,
  PiListBulletsBold,
  PiListChecksBold,
  PiMagnifyingGlassBold,
  PiMoonBold,
  PiPulseBold,
  PiQuestionBold,
  PiTerminalBold,
  PiTrashBold,
  PiWarningBold,
  PiXBold,
  PiXCircleBold,
} from 'react-icons/pi';

const ICONS = {
  unrecorded: PiCircleBold,
  passed: PiCheckCircleBold,
  command: PiTerminalBold,
  failed: PiXCircleBold,
  stale: PiClockCounterClockwiseBold,
  'earlier-failed': PiWarningBold,
  checks: PiListChecksBold,
  incomplete: PiEyeSlashBold,
  info: PiInfoBold,
  expand: PiCaretRightBold,
  remove: PiXBold,
  compass: PiCompassBold,
  copy: PiCopyBold,
  search: PiMagnifyingGlassBold,
  check: PiCheckBold,
  working: PiPulseBold,
  waiting: PiClockBold,
  quiet: PiMoonBold,
  ended: PiCheckBold,
  'worth-a-look': PiWarningBold,
  'go-to-page': PiArrowRightBold,
  'show-below': PiArrowDownBold,
  filters: PiFunnelBold,
  details: PiListBulletsBold,
  help: PiQuestionBold,
  menu: PiListBold,
  forget: PiTrashBold,
  'check-progress': PiCompassBold,
  reset: PiArrowCounterClockwiseBold,
  'caret-up': PiCaretUpBold,
  'caret-down': PiCaretDownBold,
  'caret-left': PiCaretLeftBold,
  'caret-right': PiCaretRightBold,
  tripwire: PiDiamondBold,
} as const;

export const SESSION_STATE_ICONS = {
  [SESSION_ROW_WORDS.working]: 'working',
  [SESSION_ROW_WORDS.waitingOnYou]: 'waiting',
  [SESSION_ROW_WORDS.quiet]: 'quiet',
  [SESSION_ROW_WORDS.ended]: 'ended',
} as const;

export type IconName = keyof typeof ICONS;

export function Icon({ name, ...props }: { readonly name: IconName } & IconBaseProps) {
  const Glyph = ICONS[name];
  return (
    <Glyph
      size="1.1em"
      className="shrink-0"
      {...props}
      data-icon={name}
      aria-hidden="true"
      focusable="false"
    />
  );
}
