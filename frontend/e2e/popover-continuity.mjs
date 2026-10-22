/* Browser proofs for the non-modal Popover contract. Mutations run in a scratch
   copy under this worktree and must fail at the named behavioural gate. */
import assert from 'node:assert/strict';
import { cp, mkdir, mkdtemp, readFile, rm, symlink, writeFile } from 'node:fs/promises';
import { join } from 'node:path';
import { chromium } from '@playwright/test';
import { freePorts, openPage, refreshReact, REPOSITORY } from './support/browser.mjs';
import { startReactWorld } from './support/world.mjs';
import { copyProofPath } from './support/proof-copy.mjs';
import { startIntentBoard } from './intent-board.mjs';
import { SID } from './drift-board.mjs';

const mutation = process.env.POPOVER_MUTATION || '';
const MUTATIONS = {
  'tab-guard': [
    'controls/Disclosure.tsx',
    "if (next instanceof Element && next.hasAttribute('data-base-ui-focus-guard')) return;",
    'void next;',
  ],
  'outside-focus': [
    'controls/Disclosure.tsx',
    'if (!popupRef.current?.contains(next) && !triggerNode.current?.contains(next))\n      controls.disclosures.set(disclosureKey, false);',
    'if (!popupRef.current?.contains(next) && !triggerNode.current?.contains(next)) { controls.disclosures.set(disclosureKey, false); requestAnimationFrame(() => triggerNode.current?.focus()); }',
  ],
  'inside-dismiss': [
    'controls/Disclosure.tsx',
    'ref={popupRef}',
    'ref={popupRef} onClick={() => controls.disclosures.set(disclosureKey, false)}',
  ],
  'exclusive-store': [
    'controls/Disclosure.tsx',
    'const triggerId = useId();',
    "const triggerId = useId();\n  if (open && disclosureKey.endsWith('another-why')) requestAnimationFrame(() => controls.disclosures.set(disclosureKey.replace('another-why', 'why'), false));",
  ],
  'menu-escape': [
    'controls/popoverEscape.ts',
    'owner?.focus();',
    "owner?.focus(); for (const summary of doc.querySelectorAll<HTMLElement>('details[open] > summary')) summary.click();",
  ],
  'initial-focus': ['controls/Disclosure.tsx', 'initialFocus={false}', 'initialFocus={true}'],
  'escape-all': [
    'controls/popoverEscape.ts',
    'for (const trigger of open)',
    'for (const trigger of open.slice(0, 1))',
  ],
  'escape-owner': ['controls/popoverEscape.ts', 'visible.find(', '[].find('],
  'escape-order': ['controls/popoverEscape.ts', '?? visible[0]', '?? visible.at(-1)'],
  'focus-departure': ['controls/Disclosure.tsx', 'if (!(next instanceof Node)) return;', 'return;'],
  'window-blur': [
    'controls/Disclosure.tsx',
    'if (!(next instanceof Node)) return;',
    'if (!(next instanceof Node)) { controls.disclosures.set(disclosureKey, false); return; }',
  ],
  'drop-memory': [
    'controls/Disclosure.tsx',
    'controls.disclosures.set(disclosureKey, next);',
    'void next;',
  ],
  'poll-close': [
    'controls/Disclosure.tsx',
    'const triggerId = useId();',
    'const triggerId = useId();\n  const lastChildren = useRef(children); if (open && lastChildren.current !== children) requestAnimationFrame(() => controls.disclosures.set(disclosureKey, false)); lastChildren.current = children;',
  ],
  'poll-focus': [
    'controls/Disclosure.tsx',
    'const triggerId = useId();',
    'const triggerId = useId();\n  if (open) requestAnimationFrame(() => document.getElementById(triggerId)?.focus());',
  ],
  'no-scroll': ['controls/Disclosure.tsx', 'popupRef.current?.scrollIntoView({', 'void ({'],
  'body-portal': [
    'ui/popover.tsx',
    '<PopoverPrimitive.Portal container={container} keepMounted>',
    '<PopoverPrimitive.Portal>',
  ],
  'viewport-width': [
    'ui/popover.tsx',
    'w-[min(var(--measure),calc(100vw-32px))] max-w-full',
    'w-[540px] min-w-[540px]',
  ],
  'link-target': ['styles/shell.css', '#app a,\n#app summary,', '#app summary,'],
  'live-announcement': [
    'controls/galleryWorld.ts',
    'if (region) region.textContent = text;',
    'void region;',
  ],
  'live-polite': [
    'controls/gallery.tsx',
    "region.setAttribute('aria-live', 'polite');",
    "region.setAttribute('aria-live', 'off');",
  ],
  'popup-chrome': ['ui/popover.tsx', 'bg-[var(--raise)]', 'bg-[var(--sunk)]'],
  // The production Intent heading row; without the wrap the how-to trigger shares its line at 320 px.
  'intent-wrap': ['intent/IntentSection.tsx', '<header className="flex-wrap">', '<header>'],
  modal: [
    'controls/Disclosure.tsx',
    'open={open}\n        triggerId=',
    'modal={true}\n        open={open}\n        triggerId=',
  ],
};
assert.ok(!mutation || MUTATIONS[mutation], `unknown popover mutation ${mutation}`);

const receipts = [];
const only = process.env.POPOVER_STEPS ? new RegExp(process.env.POPOVER_STEPS) : null;
const step = async (name, run) => {
  if (only && !only.test(name)) return;
  try {
    await run();
    receipts.push({ name, ok: true });
  } catch (error) {
    receipts.push({ name, ok: false, error: error.message });
    throw error;
  }
};
const patience = (ms) => (process.env.CI ? ms * 3 : ms);
const pause = (ms) => new Promise((resolve) => setTimeout(resolve, patience(ms)));
const scratch = join(REPOSITORY, 'docs/screenshots/popover-layer');
await mkdir(scratch, { recursive: true });
const copies = [];
// Each world runs in its own scratch copy. The gallery replaces the app's entry point; the Intent proof
// keeps the real entry point so it reaches the production session header. The mutation lands in every copy.
const makeCopy = async ({ gallery }) => {
  const copy = await mkdtemp(join(scratch, 'proof-'));
  copies.push(copy);
  for (const directory of ['frontend', 'compass'])
    await cp(join(REPOSITORY, directory), join(copy, directory), {
      recursive: true,
      filter: copyProofPath,
    });
  await symlink(
    join(REPOSITORY, 'node_modules'),
    join(copy, 'node_modules'),
    process.platform === 'win32' ? 'junction' : 'dir',
  );
  if (gallery)
    await writeFile(
      join(copy, 'frontend/src/main.tsx'),
      "import { mountGallery } from './controls/gallery';\nmountGallery(document.getElementById('root')!);\n",
    );
  if (mutation) {
    const [file, needle, replacement] = MUTATIONS[mutation];
    const path = join(copy, 'frontend/src', file);
    const text = await readFile(path, 'utf8');
    assert.ok(text.includes(needle), `mutation ${mutation}: missing needle`);
    await writeFile(path, text.replace(needle, replacement));
    if (mutation === 'modal') {
      const path = join(copy, 'frontend/src/ui/popover.tsx');
      const text = await readFile(path, 'utf8');
      // Base UI's modal focus/inert mode requires a Close part; live regions are
      // intentionally exempt from aria hiding, so the outside heading is checked too.
      await writeFile(
        path,
        text.replace(
          '{...props}\n        />',
          '{...props}\n        ><PopoverPrimitive.Close>Close</PopoverPrimitive.Close>{props.children}</PopoverPrimitive.Popup>',
        ),
      );
    }
  }
  return copy;
};
let world, browser, opened;
try {
  const copy = await makeCopy({ gallery: true });
  const [port, vitePort] = await freePorts(2);
  world = await startReactWorld({
    root: copy,
    port,
    vitePort,
    backendHelper: join(copy, 'frontend/e2e/controls-backend.py'),
  });
  browser = await chromium.launch();
  opened = await openPage(browser, [world.origin, world.viteOrigin], {
    viewport: { width: 1280, height: 900 },
    reducedMotion: 'reduce',
  });
  const { page } = opened;
  const trigger = (name = 'Why') => page.getByRole('button', { name, exact: true });
  const popup = () => page.getByRole('dialog', { name: 'Why', exact: true });
  const isOpen = async (name = 'Why') =>
    (await trigger(name).getAttribute('aria-expanded')) === 'true';
  const waitOpen = async (name = 'Why', open = true) => {
    await page.waitForFunction(
      ({ name, open }) =>
        [...document.querySelectorAll('[data-slot=popover-trigger]')].some(
          (el) =>
            el.textContent.trim() === name && el.getAttribute('aria-expanded') === String(open),
        ),
      { name, open },
      { timeout: patience(5000) },
    );
    await page.getByRole('dialog', { name, exact: true }).waitFor({
      state: open ? 'visible' : 'hidden',
      timeout: patience(5000),
    });
  };
  const waitFocus = async (name) => {
    await page.waitForFunction(
      (name) => document.activeElement?.textContent.trim() === name,
      name,
      { timeout: patience(5000) },
    );
  };
  const load = async () => {
    await page.route('**/api/stream', (route) =>
      route.fulfill({ contentType: 'text/event-stream', body: ': held by popover proof\n\n' }),
    );
    await page.goto(world.origin);
    await page.locator('[data-readout=displayed-accepted]').waitFor();
    await page.waitForFunction(
      () => Number(document.querySelector('[data-readout=displayed-accepted]')?.textContent) > 0,
      null,
      { timeout: patience(5000) },
    );
    await page.evaluate(() => {
      const original = Element.prototype.scrollIntoView;
      globalThis.__popoverScrolls = 0;
      Element.prototype.scrollIntoView = function (...args) {
        if (this.matches('[data-slot=popover-content]')) globalThis.__popoverScrolls += 1;
        return original.apply(this, args);
      };
    });
  };
  const open = async () => {
    await trigger().click();
    assert.equal(await isOpen(), true, 'trigger press did not write the open store');
    await waitOpen();
    await page.waitForFunction(() => globalThis.__popoverScrolls === 1, null, {
      timeout: patience(5000),
    });
  };
  const openBoth = async () => {
    await page.evaluate(() => {
      for (const name of ['why', 'another-why'])
        globalThis.__gallery.controls.disclosures.set(
          [document.getElementById('gallery').dataset.galleryProject, '', name].join('\n'),
          true,
        );
    });
    await waitOpen();
    await waitOpen('Another why');
  };
  await step(
    'opening leaves trigger focus, scrolls once and exposes popup chrome and app targets',
    async () => {
      await load();
      await open();
      assert.equal(
        await trigger().evaluate((el) => document.activeElement === el),
        true,
        'opening moved focus',
      );
      assert.equal(
        await page.evaluate(() => globalThis.__popoverScrolls),
        1,
        'opening must scroll exactly once',
      );
      assert.equal(
        await popup().evaluate((el) => Boolean(el.closest('#gallery'))),
        true,
        'portal escaped app root',
      );
      assert.equal(await popup().locator('[data-slot=popover-close]').count(), 0);
      assert.deepEqual(
        await popup().evaluate((el) => {
          const css = getComputedStyle(el);
          return {
            background: css.backgroundColor,
            border: css.borderTop,
            padding: css.padding,
            radius: css.borderRadius,
          };
        }),
        {
          background: 'rgb(50, 48, 37)',
          border: '1px solid rgb(116, 114, 95)',
          padding: '10px 12px',
          radius: '4px',
        },
        'popover chrome changed',
      );
      const link = popup().getByRole('link');
      const box = await link.boundingBox();
      assert.ok(box.width >= 44 && box.height >= 44, 'popup link lost the app target floor');
      await page.screenshot({ path: join(scratch, 'popover-desktop.png') });
    },
  );
  await step('Tab from the trigger enters the popup and keeps it open', async () => {
    await load();
    await open();
    await page.keyboard.press('Tab');
    await page.waitForFunction(
      () =>
        [...document.querySelectorAll('[data-slot=popover-content]')]
          .find(
            (el) =>
              document.getElementById(el.getAttribute('aria-labelledby'))?.textContent === 'Why',
          )
          ?.contains(document.activeElement),
      null,
      { timeout: patience(5000) },
    );
    assert.equal(await isOpen(), true, 'Tab into popup closed it');
    assert.equal(await popup().isVisible(), true, 'Tab focused hidden popup content');
    await page.keyboard.press('Tab');
    await waitFocus('Popup link');
    assert.equal(await isOpen(), true, 'Tab within popup closed it');
    assert.equal(
      await popup().evaluate((el) => el.contains(document.activeElement)),
      true,
      'Tab within popup moved focus outside',
    );
  });
  await step(
    'inside click stays open; an outside click is delivered and never steals destination focus',
    async () => {
      await load();
      await open();
      await page.getByRole('button', { name: 'Inside why', exact: true }).click();
      assert.equal(await isOpen(), true, 'inside click closed popup');
      const outside = page.getByRole('button', { name: 'Hide disclosures', exact: true });
      // A focusable destination that does not unmount the popup makes theft visible.
      const destination = page.getByRole('button', { name: 'Default action', exact: true });
      await destination.evaluate((el) => {
        globalThis.__outsideClicks = 0;
        el.addEventListener('click', () => (globalThis.__outsideClicks += 1));
      });
      await destination.click();
      await waitOpen('Why', false);
      await waitFocus('Default action');
      assert.equal(await isOpen(), false, 'outside click did not close');
      assert.equal(
        await destination.evaluate((el) => document.activeElement === el),
        true,
        'outside click stole destination focus',
      );
      assert.equal(
        await page.evaluate(() => globalThis.__outsideClicks),
        1,
        'outside click was swallowed',
      );
      assert.equal(await outside.count(), 1);
    },
  );
  await step('focus departure closes without return; window blur stays open', async () => {
    await load();
    await open();
    await page.getByRole('button', { name: 'Inside why', exact: true }).focus();
    await page.evaluate(() =>
      document.activeElement.dispatchEvent(
        new FocusEvent('focusout', { bubbles: true, relatedTarget: null }),
      ),
    );
    // Window blur has no positive state change to await; allow queued dismissal to run.
    await pause(100);
    assert.equal(await isOpen(), true, 'window blur closed popup');
    const destination = page.getByRole('button', { name: 'Default action', exact: true });
    await destination.focus();
    await waitOpen('Why', false);
    await waitFocus('Default action');
    assert.equal(await isOpen(), false, 'focus departure did not close');
    assert.equal(
      await destination.evaluate((el) => document.activeElement === el),
      true,
      'focus departure returned focus',
    );
  });
  await step(
    'Escape closes every popup and returns to the event owner through the portal',
    async () => {
      await load();
      await openBoth();
      // Dispatch at the second popup without focusing outside the first: focus departure
      // itself would correctly close the first before Escape could exercise all-open.
      await page
        .getByRole('button', { name: 'Inside another why', exact: true })
        .dispatchEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true });
      await waitOpen('Why', false);
      await waitOpen('Another why', false);
      await waitFocus('Another why');
      assert.equal(await isOpen(), false, 'Escape left first popup open');
      assert.equal(await isOpen('Another why'), false, 'Escape left second popup open');
      assert.equal(
        await trigger('Another why').evaluate((el) => document.activeElement === el),
        true,
        'Escape chose wrong portal owner',
      );
    },
  );
  await step(
    'Escape outside uses first trigger in document order and leaves the menu open',
    async () => {
      await load();
      await page.locator('summary[aria-label=More]').click();
      await openBoth();
      await page
        .getByRole('heading', { name: 'Shared controls' })
        .dispatchEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true });
      await waitOpen('Why', false);
      await waitOpen('Another why', false);
      await waitFocus('Why');
      assert.equal(await isOpen(), false);
      assert.equal(await isOpen('Another why'), false);
      assert.equal(
        await trigger().evaluate((el) => document.activeElement === el),
        true,
        'Escape did not use document order',
      );
      assert.equal(
        await page.locator('summary[aria-label=More]').evaluate((el) => el.parentElement.open),
        true,
        'Escape closed menu',
      );
    },
  );
  await step('opening another closes the first only as an outside press', async () => {
    await load();
    await open();
    await trigger('Another why').click();
    await waitOpen('Why', false);
    await waitOpen('Another why');
    await waitFocus('Another why');
    assert.equal(await isOpen(), false);
    assert.equal(await isOpen('Another why'), true);
    assert.equal(
      await trigger('Another why').evaluate((el) => document.activeElement === el),
      true,
    );
    await load();
    await openBoth();
    assert.equal(await isOpen(), true, 'external opening imposed exclusivity');
    assert.equal(await isOpen('Another why'), true);
  });
  await step(
    'a forced poll retains the same popup, focused content, open store and scroll count',
    async () => {
      await load();
      await open();
      await page.getByRole('button', { name: 'Inside why', exact: true }).focus();
      await page.evaluate(() => {
        globalThis.__popupBefore = [
          ...document.querySelectorAll('[data-slot=popover-content]'),
        ].find(
          (el) =>
            document.getElementById(el.getAttribute('aria-labelledby'))?.textContent === 'Why',
        );
        globalThis.__focusBefore = document.activeElement;
      });
      const before = Number(await page.locator('[data-readout=displayed-accepted]').textContent());
      await page.evaluate(() => globalThis.__gallery.runtime.refresh({ manual: true }));
      await page.waitForFunction(
        (number) =>
          Number(document.querySelector('[data-readout=displayed-accepted]')?.textContent) > number,
        before,
        { timeout: patience(5000) },
      );
      await waitOpen();
      await waitFocus('Inside why');
      assert.equal(await isOpen(), true, 'poll closed popup');
      assert.deepEqual(
        await page.evaluate(() => ({
          node:
            [...document.querySelectorAll('[data-slot=popover-content]')].find(
              (el) =>
                document.getElementById(el.getAttribute('aria-labelledby'))?.textContent === 'Why',
            ) === globalThis.__popupBefore,
          focus: document.activeElement === globalThis.__focusBefore,
          scrolls: globalThis.__popoverScrolls,
        })),
        { node: true, focus: true, scrolls: 1 },
        'poll disturbed popup state',
      );
    },
  );
  await step(
    'live regions announce in the accessibility tree while ordinary outside content stays exposed',
    async () => {
      await load();
      await trigger().click();
      await waitOpen();
      await page.evaluate(() =>
        globalThis.__gallery.controls.announce(
          'popover-proof',
          'Announcement while the popover is open',
        ),
      );
      const cdp = await opened.context.newCDPSession(page);
      try {
        const { nodes } = await cdp.send('Accessibility.getFullAXTree');
        const status = nodes.find((node) => node.role?.value === 'status' && !node.ignored);
        assert.ok(
          status?.properties.some(
            (property) => property.name === 'live' && property.value.value === 'polite',
          ),
          'polite live region is hidden',
        );
        assert.ok(
          nodes.some(
            (node) =>
              !node.ignored && node.name?.value === 'Announcement while the popover is open',
          ),
          'announcement is missing from accessibility tree',
        );
        assert.ok(
          nodes.some(
            (node) =>
              !node.ignored &&
              node.role?.value === 'heading' &&
              node.name?.value === 'Shared controls',
          ),
          'outside page content became inert',
        );
        await writeFile(join(scratch, 'popover-ax.json'), JSON.stringify(nodes, null, 2));
      } finally {
        await cdp.detach();
      }
    },
  );
  await step(
    'popup stays inside 320 and 375 px viewports and each at 200 percent text and viewport zoom',
    async () => {
      for (const [width, text] of [
        [320, 100],
        [375, 100],
        [160, 200],
        [188, 200],
      ]) {
        await page.setViewportSize({ width, height: 700 });
        await load();
        await page.evaluate((percent) => {
          document.documentElement.style.fontSize = `${percent}%`;
        }, text);
        await open();
        const box = await popup().boundingBox();
        assert.ok(
          box.x >= 0 && box.x + box.width <= width && box.y >= 0 && box.y + box.height <= 700,
          `popup left ${width}px viewport at ${text}%: ${JSON.stringify(box)}`,
        );
        assert.equal(
          await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth),
          true,
          'popup caused horizontal scrolling',
        );
        await page.screenshot({ path: join(scratch, `popover-${width}-${text}.png`) });
      }
    },
  );
  await step(
    'Intent how-to on the real session page wraps the Intent heading row, stays over the content beneath at 320 px, and keeps state on redraw',
    async () => {
      // The production session page, not the gallery: its Intent heading row is the one a reader sees.
      const sessionCopy = await makeCopy({ gallery: false });
      const board = await startIntentBoard({ root: sessionCopy });
      let session;
      try {
        session = await openPage(browser, [board.react.origin, board.react.viteOrigin], {
          viewport: { width: 320, height: 700 },
          reducedMotion: 'reduce',
        });
        const sessionPage = session.page;
        await sessionPage.goto(`${board.react.origin}/#n=session:w%2Falpha:claude:${SID}`);
        const name = 'How Intent and drift works';
        const howto = sessionPage.getByRole('button', { name, exact: true });
        const panel = sessionPage.getByRole('dialog', { name, exact: true });
        const heading = sessionPage.locator('#next-session-intent-heading');
        const isOpen = async () => (await howto.getAttribute('aria-expanded')) === 'true';
        const waitOpenHowTo = async (open = true) => {
          await sessionPage.waitForFunction(
            ({ name, open }) =>
              [...document.querySelectorAll('[data-slot=popover-trigger]')].some(
                (el) =>
                  el.textContent.trim() === name &&
                  el.getAttribute('aria-expanded') === String(open),
              ),
            { name, open },
            { timeout: patience(5000) },
          );
          await panel.waitFor({ state: open ? 'visible' : 'hidden', timeout: patience(5000) });
        };
        const waitFocusHowTo = () =>
          sessionPage.waitForFunction(
            (name) => document.activeElement?.textContent.trim() === name,
            name,
            { timeout: patience(5000) },
          );
        await heading.waitFor({ timeout: patience(5000) });
        await howto.waitFor({ state: 'visible', timeout: patience(5000) });
        // At 100 percent text a 320 px header holds the heading and trigger on one line, so the wrap class only
        // matters once the text is 200 percent, the reflow condition the popover step below also uses.
        await sessionPage.evaluate(() => {
          document.documentElement.style.fontSize = '200%';
        });
        await pause(200);
        assert.equal(
          await heading.evaluate((el) => getComputedStyle(el.parentElement).flexWrap),
          'wrap',
          'the Intent heading row no longer wraps',
        );
        const headingBox = await heading.boundingBox();
        const triggerBox = await howto.boundingBox();
        assert.ok(
          triggerBox.y >= headingBox.y + headingBox.height - 1,
          `the how-to trigger shares the Intent heading line at 320 px: ${JSON.stringify({ headingBox, triggerBox })}`,
        );
        await howto.click();
        await waitOpenHowTo();
        assert.equal(await isOpen(), true, 'trigger press did not open the how-to');
        assert.match(await panel.innerText(), /Compass never writes into sessions/);
        assert.match(await panel.innerText(), /Not enough recorded yet/);
        const box = await panel.boundingBox();
        assert.ok(
          box.x >= 0 && box.x + box.width <= 320 && box.y >= 0 && box.y + box.height <= 700,
          'how-to left 320 px viewport',
        );
        // The popup must be painted over the Intent card it opens from: the point at the centre of their
        // overlap has to hit the popup, not the content beneath it.
        const beneath = await sessionPage.locator('.next-cockpit-held').boundingBox();
        const left = Math.max(box.x, beneath.x);
        const right = Math.min(box.x + box.width, beneath.x + beneath.width);
        const top = Math.max(box.y, beneath.y);
        const bottom = Math.min(box.y + box.height, beneath.y + beneath.height);
        assert.ok(right > left && bottom > top, 'the how-to popup overlaps no content beneath it');
        assert.equal(
          await panel.evaluate(
            (el, [x, y]) => el.contains(document.elementFromPoint(x, y)),
            [(left + right) / 2, (top + bottom) / 2],
          ),
          true,
          'content beneath the how-to paints over the popup',
        );
        await panel.screenshot({ path: join(scratch, 'intent-howto-320.png') });
        const update = sessionPage.waitForResponse((response) =>
          response.url().includes('/api/data'),
        );
        await refreshReact(sessionPage, true);
        await update;
        await pause(500);
        await waitOpenHowTo();
        await sessionPage.keyboard.press('Escape');
        await waitOpenHowTo(false);
        await waitFocusHowTo();
        await howto.press('Enter');
        await waitOpenHowTo();
        await howto.press('Space');
        await waitOpenHowTo(false);
        await howto.press('Space');
        await waitOpenHowTo();
        await heading.click();
        await waitOpenHowTo(false);
        assert.deepEqual(session.log.externalRequests, []);
        assert.deepEqual(session.log.pageErrors, []);
        assert.deepEqual(session.log.consoleErrors, []);
      } finally {
        await session?.close();
        await board.close();
      }
    },
  );
  assert.deepEqual(opened.log.externalRequests, []);
  assert.deepEqual(opened.log.pageErrors, []);
  assert.deepEqual(opened.log.consoleErrors, []);
} finally {
  console.log(
    JSON.stringify(
      { mutation: mutation || null, receipts, pageErrors: opened?.log.pageErrors },
      null,
      2,
    ),
  );
  await opened?.close();
  await browser?.close();
  await world?.close();
  for (const copy of copies) await rm(copy, { recursive: true, force: true });
}
