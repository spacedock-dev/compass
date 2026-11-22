import type { Meta, StoryObj } from '@storybook/react-vite';
import { expect } from 'storybook/test';
import { Icon, type IconName } from '../src/ui/icons';
const glyphs = [
  ['working', 'Working', 'PiPulseBold'],
  ['waiting', 'Waiting on you', 'PiClockBold'],
  ['quiet', 'Quiet', 'PiMoonBold'],
  ['ended', 'Ended', 'PiCheckBold'],
  ['worth-a-look', 'Worth a look', 'PiWarningBold'],
  ['go-to-page', 'go-to-page', 'PiArrowRightBold'],
  ['show-below', 'show-below', 'PiArrowDownBold'],
  ['filters', 'filters', 'PiFunnelBold'],
  ['details', 'details', 'PiListBulletsBold'],
  ['help', 'help', 'PiQuestionBold'],
  ['menu', 'menu', 'PiListBold'],
  ['forget', 'forget', 'PiTrashBold'],
  ['check-progress', 'check-progress', 'PiCompassBold'],
  ['reset', 'reset', 'PiArrowCounterClockwiseBold'],
  ['caret-up', 'caret-up', 'PiCaretUpBold'],
  ['caret-down', 'caret-down', 'PiCaretDownBold'],
  ['caret-left', 'caret-left', 'PiCaretLeftBold'],
  ['caret-right', 'caret-right', 'PiCaretRightBold'],
  ['tripwire', 'tripwire', 'PiDiamondBold'],
  ['unrecorded', 'unrecorded', 'PiCircleBold'],
  ['passed', 'passed', 'PiCheckCircleBold'],
  ['command', 'command', 'PiTerminalBold'],
  ['failed', 'failed', 'PiXCircleBold'],
  ['stale', 'stale', 'PiClockCounterClockwiseBold'],
  ['earlier-failed', 'earlier-failed', 'PiWarningBold'],
  ['checks', 'checks', 'PiListChecksBold'],
  ['incomplete', 'incomplete', 'PiEyeSlashBold'],
  ['info', 'info', 'PiInfoBold'],
  ['expand', 'expand', 'PiCaretRightBold'],
  ['compass', 'compass', 'PiCompassBold'],
  ['copy', 'copy', 'PiCopyBold'],
  ['search', 'search', 'PiMagnifyingGlassBold'],
  ['check', 'check', 'PiCheckBold'],
] as const satisfies readonly (readonly [IconName, string, string])[];
const meta = { title: 'UI/Icons', component: Icon, args: { name: 'unrecorded' } } satisfies Meta<
  typeof Icon
>;
export default meta;
type Story = StoryObj<typeof meta>;
export const Family: Story = {
  render: () => (
    <table style={{ borderCollapse: 'collapse', minWidth: 'min(100%, 30rem)' }}>
      <thead>
        <tr>
          <th scope="col" style={{ textAlign: 'start' }}>
            Icon
          </th>
          <th scope="col" style={{ textAlign: 'start' }}>
            Phosphor Bold source
          </th>
        </tr>
      </thead>
      <tbody>
        {glyphs.map(([name, label, source]) => (
          <tr key={name}>
            <th
              scope="row"
              style={{ fontWeight: 600, textAlign: 'start', padding: '.35rem 1.5rem .35rem 0' }}
            >
              <span style={{ display: 'inline-flex', alignItems: 'center', gap: 'var(--sp-2)' }}>
                <Icon name={name} size="1.25em" />
                {label}
              </span>
            </th>
            <td>{source}</td>
          </tr>
        ))}
      </tbody>
    </table>
  ),
  play: async ({ canvasElement }) => {
    await expect(canvasElement.querySelectorAll('svg')).toHaveLength(glyphs.length);
    for (const [name, , source] of glyphs) {
      const glyph = canvasElement.querySelector(`svg[data-icon="${name}"]`);
      await expect(glyph, name).toBeVisible();
      await expect(glyph?.closest('tr')).toHaveTextContent(source);
      await expect(glyph).toHaveAttribute('aria-hidden', 'true');
      await expect(glyph).toHaveAttribute('focusable', 'false');
    }
  },
};
