import { describe, expect, it } from 'vitest';
import { firstShapeDifference, shape } from '../delegation/dom.test.helper';
import { mulberry32, pick } from '../observed/generate.test.helper';
import { mountPanels } from '../steering/testing';
import { allowUnreadGoldens } from '../../test/legacy_goldens';
import { CapacityStrip } from './CapacityStrip';
import { genCapacity } from './generate.test.helper';
import { heldFor } from './held';
import { loadLegacyCapacity, type LegacyConsent } from './legacy.test.helper';

/* The strip is held to the legacy page by what a reader can read and press. The page's own `nextCapacityView`
   runs over a generated board, in each consent state and with a selection that is published, buried below
   the initial rows or no longer published, and so does the component; both are reduced to one tree and
   compared: every row with its bar, pace, end and reset, the model lines, the "more windows" count and the
   prospect. The selection each leaves behind is compared too.

   The quota disclosure and switch are left out of the comparison on purpose: on 2026-10-27 the fetch became
   on until turned off, with one line in place of the page's question, so the recorded answers no longer
   describe it (docs/design-frontend-migration.md, "Held to recorded answers"). `UsageConsent.test.tsx` holds
   that line instead.

   One deliberate difference is normalised: the page printed "and null readings" for a recent pace measured at
   zero whose reading count was not published, which is a number replaced by an absence; the port leaves the
   clause out. */
allowUnreadGoldens(
  'The Console rail answers recorded for the quota question are no longer asked: on 2026-10-27 the quota fetch became on until turned off, with one line in place of the question.',
);
const legacy = loadLegacyCapacity();
const CASES = 80;
const SEEDS = CASES;
const CONSENT = 'compass.next.usage.consent';

const QUOTA_LINE = '[data-next-usage-consent], .next-usage-switch';
const parse = (html: string): Element[] => {
  const template = document.createElement('template');
  template.innerHTML = html.replace(' and null readings', '');
  return [...template.content.children].filter((node) => !node.matches(QUOTA_LINE));
};

describe('the capacity strip agrees with the legacy page', () => {
  it(`over ${String(SEEDS)} generated boards in every consent state`, async () => {
    const failures: string[] = [];
    const seen = {
      drawn: 0,
      more: 0,
      models: 0,
      prospect: 0,
      buried: 0,
      stale: 0,
    };
    for (let seed = 1; seed <= SEEDS && failures.length < 3; seed += 1) {
      const rnd = mulberry32(seed * 31 + 7);
      const { payload, keys } = genCapacity(seed);
      const consent = pick<LegacyConsent>(rnd, [null, 'granted', 'declined']);
      const selected = pick(rnd, ['', 'ghost:week', ...keys, ...keys]);
      const html = legacy.view(payload, { consent, selected });
      const page = mountPanels(
        (shell) => {
          heldFor(shell.runtime).selection.set(selected);
          return (
            <div data-test-root="">
              <CapacityStrip />
            </div>
          );
        },
        { data: payload, strict: false, storage: consent ? { [CONSENT]: consent } : {} },
      );
      await page.settle();
      const mine = [...(page.container.querySelector('[data-test-root]')?.children ?? [])].filter(
        (node) => !node.matches(QUOTA_LINE),
      );
      const theirs = parse(html);
      const label = `seed ${String(seed)} consent ${String(consent)} selected ${JSON.stringify(selected)}`;
      if (theirs.length !== mine.length) {
        failures.push(`${label}: ${String(theirs.length)} blocks != ${String(mine.length)}`);
      } else {
        for (let index = 0; index < theirs.length; index += 1) {
          const found = firstShapeDifference(
            shape(theirs[index] as Element),
            shape(mine[index] as Element),
          );
          if (found) {
            failures.push(`${label} block ${String(index)}: ${found}`);
            break;
          }
        }
      }
      const held = heldFor(page.shell.runtime).selection.read();
      if (held !== legacy.selected()) {
        failures.push(
          `${label}: held selection ${JSON.stringify(held)} != ${JSON.stringify(legacy.selected())}`,
        );
      }
      const root = page.container;
      seen.drawn += root.querySelector('[data-next-capacity]') ? 1 : 0;
      seen.more += root.querySelector('.next-capacity-more') ? 1 : 0;
      seen.models += root.querySelector('[data-next-capacity-models]') ? 1 : 0;
      seen.prospect += root.querySelector('.next-capacity-prospect') ? 1 : 0;
      seen.stale += root.querySelector('.next-capacity-prospect small') ? 1 : 0;
      const pressed = root.querySelector('button[aria-pressed="true"]');
      const rows = [...root.querySelectorAll('[data-next-capacity-row]')];
      seen.buried +=
        pressed && rows.length === 3 && pressed.closest('[data-next-capacity-row]') === rows[2]
          ? 1
          : 0;
      page.unmount();
    }
    expect(failures).toEqual([]);
    // The comparison is not vacuous: every branch the strip words differently is reached.
    expect(seen.drawn).toBeGreaterThan(30);
    expect(seen.more).toBeGreaterThan(6);
    expect(seen.models).toBeGreaterThan(2);
    expect(seen.prospect).toBeGreaterThan(10);
    expect(seen.stale).toBeGreaterThan(2);
    expect(seen.buried).toBeGreaterThan(0);
  }, 240_000);
});
