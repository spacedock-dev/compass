import { describe, expect, it } from 'vitest';
import { mulberry32, pick } from '../observed/generate.test.helper';
import { mountPanels } from '../steering/testing';
import { allowUnreadGoldens } from '../../test/legacy_goldens';
import { CapacityStrip } from './CapacityStrip';
import { genCapacity } from './generate.test.helper';
import { heldFor } from './held';
import { loadLegacyCapacity, type LegacyConsent } from './legacy.test.helper';

/* The new card speaks for one window. Compare its selection and measured figure with the corresponding
   recorded row. The former table, consent line and placement of the pace details have browser or
   mounted proofs of their own. docs/design-frontend-migration.md#held-to-recorded-answers */
allowUnreadGoldens(
  'The Console rail answers recorded for the quota question are no longer asked: the quota fetch became on until turned off, with one line in place of the question.',
);
const legacy = loadLegacyCapacity();
const SEEDS = 80;
const CONSENT = 'compass.next.usage.consent';

describe('the allowance card keeps the recorded choice and measured figure', () => {
  it(`over ${String(SEEDS)} generated boards in every consent state`, async () => {
    const seen = { read: 0, off: 0, absent: 0, multiple: 0 };
    for (let seed = 1; seed <= SEEDS; seed += 1) {
      const rnd = mulberry32(seed * 31 + 7);
      const { payload, keys } = genCapacity(seed);
      const consent = pick<LegacyConsent>(rnd, [null, 'granted', 'declined']);
      const selected = pick(rnd, ['', 'ghost:week', ...keys, ...keys]);
      const recorded = document.createElement('template');
      recorded.innerHTML = legacy.view(payload, { consent, selected });
      const picked = legacy.selected();
      const windows = [...recorded.content.querySelectorAll('[data-next-capacity-row]')];
      const measured = windows
        .find((node) => node.getAttribute('data-next-capacity-row') === picked)
        ?.querySelector('.next-capacity-pct')
        ?.textContent?.replace(/^USED\s*/, '')
        .trim();

      const page = mountPanels(
        (shell) => {
          heldFor(shell.runtime).selection.set(selected);
          return <CapacityStrip />;
        },
        { data: payload, strict: false, storage: consent ? { [CONSENT]: consent } : {} },
      );
      await page.settle();
      expect(heldFor(page.shell.runtime).selection.read(), `seed ${String(seed)}`).toBe(picked);
      const bars = page.container.querySelectorAll('progress');
      if (consent === 'declined') {
        seen.off += 1;
        expect(bars).toHaveLength(0);
      } else if (picked) {
        seen.read += 1;
        expect(bars).toHaveLength(1);
        expect(measured).toBe(`${bars[0]?.getAttribute('value')}%`);
        const choices = [...page.container.querySelectorAll('button[data-next-capacity-row]')];
        if (windows.length > 1) {
          seen.multiple += 1;
          expect(choices.map((node) => node.getAttribute('data-next-capacity-row'))).toEqual(
            windows.map((node) => node.getAttribute('data-next-capacity-row')),
          );
        } else {
          expect(choices).toHaveLength(0);
        }
      } else {
        seen.absent += 1;
        expect(bars).toHaveLength(0);
      }
      page.unmount();
    }
    for (const count of Object.values(seen)) expect(count).toBeGreaterThan(0);
  }, 240_000);
});
