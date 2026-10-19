import assert from 'node:assert/strict';
import { call, startIntentBoard } from '../intent-board.mjs';
import {
  ASSESSMENT,
  SAVED,
  RECORD,
  POLICY,
  UNCONSENTED,
  ROUTE,
  fact,
  freshScript,
  installScript,
} from '../drift-board.mjs';
import { openPage } from './browser.mjs';
import { join } from 'node:path';
import { awaitRecordRead } from './record.mjs';

/* Live levels and a superseded result are absent from the ordinary route census. */
export async function visitIntentDisplayStates(browser, root, record) {
  const board = await startIntentBoard({ root });
  try {
    const g = (await call(board.react.origin, 'GET', '/api/data')).body.generated;
    for (const width of [1280, 375]) {
      const opened = await openPage(browser, [board.react.origin, board.react.viteOrigin], {
        viewport: { width, height: 900 },
      });
      try {
        await opened.context.addInitScript(() =>
          localStorage.setItem('compass.next.live-estimate:claude:intent-2', '1'),
        );
        const script = freshScript();
        await installScript(opened.context, script);
        for (const state of width === 1280
          ? ['live', 'stale', 'job', 'consent', 'log', 'draft']
          : ['live', 'stale']) {
          for (const key of Object.keys(script)) delete script[key];
          Object.assign(script, freshScript(), {
            session: {
              ...SAVED(g),
              state: 'idle',
              turn_end_at: g - 200,
              reading_eligibility: undefined,
              ...(state === 'stale'
                ? {
                    annotation_revision: 4,
                    annotation_assessment: ASSESSMENT(g),
                    annotation_reading_count: 1,
                  }
                : {}),
            },
            payload: {
              reading: state === 'consent' ? UNCONSENTED : POLICY,
              reading_routes: { claude: ROUTE },
              reading_check: 'accepted',
              reading_jobs:
                state === 'job'
                  ? {
                      'claude:intent-2': {
                        id: 'chrome-job',
                        phase: 'read',
                        steps: [{ phase: 'read', text: 'Reading the record' }],
                      },
                    }
                  : {},
            },
            facts: [fact('anchor', g - 900), ...RECORD(g)],
            work:
              state === 'live'
                ? {
                    live_levels: [
                      {
                        harness: 'claude',
                        sid: 'intent-2',
                        level: 'high',
                        revision: 3,
                        computed_at: g - 60,
                        reasons: ['failed-check', 'no-passing-check'],
                        cites: ['c1'],
                        rose_from: 'medium',
                        rose_at: 'c1',
                      },
                    ],
                  }
                : {},
          });
          if (state === 'draft') script.session = {};
          await opened.page.goto('about:blank');
          await opened.page.goto(
            board.react.origin +
              (state === 'log' ? '/#n=intent' : '/#n=session:w%2Falpha:claude:intent-2'),
          );
          if (state === 'log') await opened.page.locator('[data-next-view-body=intent]').waitFor();
          else await awaitRecordRead(opened.page);
          if (state === 'draft')
            await opened.page.locator('[data-next-cockpit-draft-marks]').waitFor();
          if (state === 'consent') {
            await opened.page.locator('[data-next-cockpit-action=reading-ask]').click();
            await opened.page.locator('[data-slot=card][data-variant=reading-consent]').waitFor();
          }
          if (state === 'live' || state === 'stale') {
            await opened.page
              .locator(state === 'live' ? '[data-next-drift-pill]' : '[data-next-result-stale]')
              .waitFor();
            assert.equal(
              await opened.page.locator('[data-next-drift-pill]').count(),
              state === 'live' ? 1 : 0,
            );
          }
          await opened.page.evaluate(() => document.fonts.ready);
          if (process.env.COMPASS_SCREENSHOTS)
            await opened.page.screenshot({
              path: join(process.env.COMPASS_SCREENSHOTS, `chrome-${state}-${width}.png`),
              fullPage: true,
            });
          await record(opened.page, `Intent ${state} at ${width}`);
        }
      } finally {
        await opened.close();
      }
    }
  } finally {
    await board.close();
  }
}
