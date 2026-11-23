import { expect, it } from 'vitest';
import { testControls } from '../controls/testControls';
import { fullActivityKey, showActivityLog } from './fullActivityKey';

it('a citation opens Activity log from a previously selected Evidence tab', () => {
  const { controls } = testControls();
  const session = { harness: 'claude', sid: 's1' };
  const key = fullActivityKey('demo', session);
  controls.technicalTabs.remember(key, 'evidence');

  showActivityLog(controls, 'demo', session);

  expect(controls.technicalTabs.read(key)).toBe('activity-log');
  expect(controls.disclosures.isOpen(key)).toBe(true);
});
