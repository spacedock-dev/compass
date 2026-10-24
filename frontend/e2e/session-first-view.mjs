import assert from 'node:assert/strict';
import { mkdir, writeFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import { chromium } from '@playwright/test';
import { startIntentBoard } from './intent-board.mjs';
import { installScript, freshScript, POLICY, ROUTE, SAVED, SID } from './drift-board.mjs';
import { proveFirstViewStates } from './support/session-first-view-states.mjs';
import { openPage, refreshReact } from './support/browser.mjs';

const root = fileURLToPath(new URL('../../', import.meta.url));
const inventoryOnly = process.env.FIRST_VIEW_INVENTORY_ONLY === '1';
const board = await startIntentBoard({ root });
const browser = await chromium.launch();
const opened = await openPage(browser, [board.react.origin, board.react.viteOrigin], {
  viewport: { width: 1280, height: 800 },
});
const { page } = opened;
const script = freshScript();
script.session = { state: 'working', reading_eligibility: undefined };
script.payload = {
  reading: POLICY,
  reading_routes: { claude: ROUTE },
  reading_check: 'accepted',
  reading_jobs: {},
};
await installScript(opened.context, script);
const inventory = () =>
  page.evaluate(() => {
    const root = document.querySelector('[data-next-session-detail]');
    return [
      ...root.querySelectorAll('button,a,summary,select'),
      ...document.querySelectorAll('nav[aria-label="Breadcrumb"] a'),
    ]
      .filter((el) => {
        const css = getComputedStyle(el);
        return (
          !el.closest('[hidden]') &&
          el.getClientRects().length &&
          css.visibility !== 'hidden' &&
          Number(css.opacity) !== 0
        );
      })
      .map((el) => ({
        label: el.hasAttribute('data-next-cockpit-prompt-select')
          ? 'Use your prompt'
          : (el.getAttribute('aria-label') || el.textContent).replace(/\s+/g, ' ').trim(),
        top: Math.round(el.getBoundingClientRect().top),
        inActivity: Boolean(el.closest('[data-next-session-activity]')),
        inFirstView:
          el.getBoundingClientRect().top < innerHeight && el.getBoundingClientRect().bottom > 0,
      }));
  });
try {
  await page.goto(`${board.react.origin}/#n=session:w%2Falpha:claude:${SID}`);
  await page.locator('[data-next-cockpit-drafted]').waitFor();
  await page.locator('[data-next-cockpit-action="reading-ask"]').waitFor();
  await page.waitForTimeout(500);
  if (process.env.FIRST_VIEW_MUTATION === 'extra-control')
    await page.evaluate(() => {
      const button = document.createElement('button');
      button.textContent = 'Unexpected control';
      document.querySelector('[data-next-session-panel]').prepend(button);
    });
  const before = await inventory();
  await mkdir(`${root}docs/screenshots`, { recursive: true });
  await writeFile(
    `${root}docs/screenshots/session-first-view-${process.env.FIRST_VIEW_MUTATION ? 'mutation' : inventoryOnly ? 'before' : 'after'}.json`,
    JSON.stringify(before, null, 2),
  );
  console.log(
    JSON.stringify({
      inventory: before,
      total: before.length,
      firstView: before.filter((item) => item.inFirstView).length,
    }),
  );
  if (!inventoryOnly) {
    assert.notEqual(
      await page.locator('[data-next-cockpit-action="reading-ask"]').getAttribute('aria-disabled'),
      'true',
      'running reads the work so far',
    );
    assert.equal(
      await page.locator('[data-next-cockpit-action="reading-ask"]').getAttribute('data-variant'),
      'primary',
    );
    const allowed = new Set([
      'How Intent and drift works',
      'Use your prompt',
      'Save intent',
      'Analyze drift',
      'What is sent',
      'More',
      'w/alpha',
      'Sessions',
    ]);
    assert.equal(before.length, 14, 'one extra or missing control changes the complete inventory');
    // The signed set is the Intent and drift side and the page chrome. The activity column on the left is the
    // session's own record: its disclosures may show beside the panel, and are held to the complete inventory above.
    const signed = before.filter((item) => item.inFirstView && !item.inActivity);
    assert.ok(
      signed.every((item) => allowed.has(item.label)),
      'one extra control violates the signed first-view set',
    );
    assert.ok(signed.length <= 8, 'first view has more than eight controls');
    for (const viewport of [
      { width: 1280, height: 800 },
      { width: 375, height: 667 },
      { width: 320, height: 667 },
      { width: 640, height: 400 },
    ]) {
      await page.setViewportSize(viewport);
      await page.evaluate(() => scrollTo(0, 0));
      await page.screenshot({
        path: `${root}docs/screenshots/session-first-view-${viewport.width}.png`,
        fullPage: true,
      });
      const bounds = await page.evaluate(() => {
        const box = (selector) => {
          const r = document.querySelector(selector).getBoundingClientRect();
          return { top: r.top, bottom: r.bottom, left: r.left, right: r.right };
        };
        return {
          goal: box('[data-next-cockpit-held-kind="goal"]'),
          primary: box('[data-next-cockpit-action="reading-ask"]'),
          panel: box('[data-next-session-panel]'),
          activity: box('[data-next-session-activity]'),
          height: innerHeight,
          width: innerWidth,
          scroll: document.documentElement.scrollWidth,
        };
      });
      if (viewport.width === 1280 || viewport.width === 375)
        assert.ok(
          bounds.goal.top >= 0 && bounds.goal.bottom <= bounds.height,
          `goal outside viewport ${JSON.stringify({ viewport, bounds })}`,
        );
      if (viewport.width === 1280 || viewport.width === 375)
        assert.ok(
          bounds.primary.top >= 0 && bounds.primary.bottom <= bounds.height,
          `primary outside viewport ${JSON.stringify({ viewport, bounds })}`,
        );
      assert.ok(bounds.scroll <= bounds.width + 1, `horizontal overflow ${viewport.width}`);
      // Wide: the activity reads on the left and the Intent and drift panel on the right, level at the top.
      // Narrow: one column, with the panel first so the goal stays in the first view.
      if (viewport.width === 1280)
        assert.ok(
          bounds.panel.left >= bounds.activity.right - 1 &&
            Math.abs(bounds.panel.top - bounds.activity.top) <= 2,
          `panel is not beside the activity ${JSON.stringify({ viewport, bounds })}`,
        );
      else if (viewport.width <= 1100)
        assert.ok(
          bounds.panel.bottom <= bounds.activity.top + 1,
          `panel does not lead the single column ${JSON.stringify({ viewport, bounds })}`,
        );
      console.log(JSON.stringify({ viewport, bounds }));
    }
    await page.setViewportSize({ width: 1280, height: 800 });
    await page.getByRole('button', { name: 'More', exact: true }).click();
    await page.getByRole('switch', { name: 'Live monitor' }).waitFor({ state: 'visible' });
    await page
      .getByText(
        'Shows a level after every turn, from checks and file paths, with no model call. The level shows here and in the header.',
        { exact: true },
      )
      .waitFor({ state: 'visible' });
    await page
      .getByText('Drift is measured against these. Edit anything that is off.', { exact: true })
      .waitFor({ state: 'visible' });
    await page.getByRole('button', { name: 'Clear', exact: true }).waitFor({ state: 'visible' });
    await page
      .getByRole('button', { name: 'Pause model calls', exact: true })
      .waitFor({ state: 'visible' });
    const update = page.waitForResponse((response) => response.url().includes('/api/data'));
    await refreshReact(page, true);
    await update;
    await page.waitForTimeout(500);
    assert.equal(
      await page.getByRole('button', { name: 'More', exact: true }).getAttribute('aria-expanded'),
      'true',
    );
    await page.getByRole('button', { name: 'More', exact: true }).click();
    const words = await page.locator('[data-next-session-panel]').evaluate((root) => {
      const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
      const words = [];
      while (walker.nextNode()) {
        const parent = walker.currentNode.parentElement;
        if (
          !parent ||
          parent.closest('textarea,[data-slot=select-trigger],[hidden],.next-visually-hidden')
        )
          continue;
        if (parent.getClientRects().length) words.push(walker.currentNode.textContent);
      }
      return words.join(' ').trim().split(/\s+/).length;
    });
    assert.ok(words <= 90, `idle panel word ceiling: ${words}`);
    console.log(JSON.stringify({ idlePanelWords: words, ceiling: 90 }));
    await page.getByRole('button', { name: 'What is sent', exact: true }).click();
    await page.getByText('Your saved words.', { exact: true }).waitFor({ state: 'visible' });
    await page.getByText('The agent messages.', { exact: true }).waitFor({ state: 'visible' });
    await page
      .getByText(
        'What it reads is the evidence on this page: the observed record in this session’s activity and the goal and output you saved, and nothing else. It does not read a diff, a file, a test or a deliverable, replies from git, gh or connected tools, or your screen.',
        { exact: true },
      )
      .waitFor({ state: 'visible' });
    await page.keyboard.press('Escape');
    const generated = (await (await fetch(`${board.react.origin}/api/data`)).json()).generated;
    script.session = {
      ...SAVED(generated),
      state: 'working',
      reading_eligibility: undefined,
      delegated_launches: 1,
      delegated_unpaired: 1,
      delegated_visibility: 'partial',
    };
    await page.reload();
    await page
      .locator('.next-cockpit-reading-count')
      .getByText(/model requests?$/)
      .waitFor({ state: 'visible' });
    await page.getByText('9 of 10 left today', { exact: true }).waitFor({ state: 'visible' });
    await page.getByRole('button', { name: 'More', exact: true }).click();
    // The Drift card draws no Delegated work line (amended 2026-10-21): launches surface only in At risk.
    if (await page.getByText(/Delegated work/).count()) {
      throw new Error('More still draws a Delegated work line');
    }
    await page.getByRole('button', { name: /Saved.*reads from/ }).click();
    await page
      .getByText(
        'Editing the goal or adding a line keeps this start. Read from my latest message moves it.',
        {
          exact: true,
        },
      )
      .waitFor({ state: 'visible' });
    await page.getByRole('button', { name: 'Discard everything', exact: true }).click();
    await page
      .getByRole('button', { name: 'Discard everything', exact: true })
      .last()
      .waitFor({ state: 'visible' });
    /* Predates the one-column page (2026-10-19): the session More is gone, so this count fails when the proof
       is run on demand until it is brought forward to the Intent and Drift cards that now hold those parts. */
    assert.equal(
      await page.locator('[data-next-session-more-items]').evaluate((node) => node.children.length),
      6,
    );
    const inertStates = [
      {
        name: 'idle without a recorded stop',
        session: { state: 'idle', reading_eligibility: { ok: false, reason: 'idle-unknown' } },
        payload: {},
        line: 'Analyze opens while this session runs.',
      },
      {
        name: 'end settling',
        session: {
          state: 'idle',
          ended_at: generated - 1,
          reading_eligibility: { ok: false, reason: 'settling', until: generated + 60 },
        },
        payload: {},
        line: 'Ready in a few seconds.',
      },
      {
        name: 'no reader',
        session: { state: 'working', reading_eligibility: undefined },
        payload: {
          reading_routes: { claude: { provider: '', note: 'No reader on this machine.' } },
        },
        line: 'No reader on this machine.',
      },
      {
        name: 'annotations off',
        session: { state: 'working', reading_eligibility: undefined },
        payload: { annotate: false },
        line: 'Annotations are off for this run. Start without --no-annotations to type a goal and an expected output here.',
      },
    ];
    for (const fixture of inertStates) {
      script.session = fixture.session;
      script.payload = {
        reading: POLICY,
        reading_routes: { claude: ROUTE },
        reading_check: 'accepted',
        reading_jobs: {},
        ...fixture.payload,
      };
      await page.reload();
      await page
        .locator('.next-session-drift-check')
        .getByText(fixture.line, { exact: true })
        .waitFor({ state: 'visible' });
      const button = page.locator('[data-next-cockpit-action="reading-ask"]');
      if (fixture.name === 'no reader') assert.equal(await button.count(), 0);
      else assert.equal(await button.getAttribute('aria-disabled'), 'true', fixture.name);
      console.log(JSON.stringify({ inert: fixture.name, sentence: fixture.line }));
    }
    await proveFirstViewStates({ page, browser, board, script });
    assert.equal(opened.log.nonGet.length, 0);
    assert.deepEqual(opened.log.externalRequests, []);
  }
} finally {
  await opened.close();
  await browser.close();
  await board.close();
}
