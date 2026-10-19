import assert from 'node:assert/strict';
import { cp, mkdir, mkdtemp, readFile, rm, symlink, writeFile } from 'node:fs/promises';
import { join } from 'node:path';
import { chromium } from '@playwright/test';
import { call, startIntentBoard } from './intent-board.mjs';
import {
  ASSESSMENT,
  HARNESS,
  SID,
  ROUTE,
  UNCONSENTED,
  RECORD,
  fact,
  freshScript,
  installScript,
  postsTo,
  quietWhenClosing,
} from './drift-board.mjs';
import { openPage, REPOSITORY } from './support/browser.mjs';
import { copyProofPath } from './support/proof-copy.mjs';
import { awaitRecordRead } from './support/record.mjs';

const mutation = process.env.JOURNEY_MUTATION || '';
const MUTATIONS = {
  'confirm-step': [
    'drift/ReadingControl.tsx',
    "const label = confirming ? 'Allow and analyze' : again ? 'Analyze again' : 'Analyze drift';",
    "const label = confirming && !confirmed ? 'Confirm analysis' : confirming ? 'Allow and analyze' : again ? 'Analyze again' : 'Analyze drift';",
  ],
};
assert.ok(!mutation || MUTATIONS[mutation], `unknown journey mutation ${mutation}`);

// DEC-27 counts activations, including entry into the goal box, rather than calls to a click helper.
// Enter generates one trusted click on a button or link; focus and typing generate none.
function countActivations() {
  globalThis.__journey = { counting: false, clicks: [], initialStorage: Object.keys(localStorage) };
  document.addEventListener(
    'click',
    (event) => {
      const control = event.target.closest(
        'button,a,input,textarea,select,summary,[role="button"],[role="option"]',
      );
      if (!event.isTrusted || !control || !globalThis.__journey.counting) return;
      globalThis.__journey.clicks.push(
        control.getAttribute('aria-label') ||
          control.getAttribute('data-next-cockpit-held-kind') ||
          control.textContent.trim(),
      );
    },
    true,
  );
}

const cases = [
  ...['running', 'ended', 'turn-stop'].flatMap((state) => [
    { name: `draft-${state}`, state, budget: 3 },
    { name: `directions-${state}`, state, later: true, budget: 4 },
  ]),
  { name: 'chosen-prompt-running', state: 'running', chosen: true, budget: 5 },
  { name: 'draft-no-departure', state: 'running', noDeparture: true, budget: 3 },
  { name: 'typed-over-draft', state: 'running', typed: true, budget: 5 },
  { name: 'typed-no-draft', state: 'running', typed: true, noDraft: true, budget: 4 },
  { name: 'typed-ended-refused', state: 'ended', typed: true, refused: true, budget: 4 },
  { name: 'idle-no-stop', state: 'idle', refused: true, budget: 2 },
];
const receipts = [];
const scratch = join(REPOSITORY, 'docs/screenshots/journey-budget');
await mkdir(scratch, { recursive: true });
const root = await mkdtemp(join(scratch, 'proof-'));
let browser;
try {
  // A production scratch build exercises these layers' sources without replacing tracked page bytes.
  for (const directory of ['frontend', 'compass'])
    await cp(join(REPOSITORY, directory), join(root, directory), {
      recursive: true,
      filter: copyProofPath,
    });
  await symlink(
    join(REPOSITORY, 'node_modules'),
    join(root, 'node_modules'),
    process.platform === 'win32' ? 'junction' : 'dir',
  );
  if (mutation) {
    const [file, needle, replacement] = MUTATIONS[mutation];
    const path = join(root, 'frontend/src', file);
    const source = await readFile(path, 'utf8');
    assert.equal(source.split(needle).length, 2, 'confirm mutation lost its unique target');
    const press = 'if (identity) {\n          void askForReading';
    assert.ok(source.includes(press), 'confirm mutation lost its press target');
    await writeFile(
      path,
      source
        .replace('useEffect, type ReactNode', 'useEffect, useState, type ReactNode')
        .replace(needle, replacement)
        .replace(
          'const { session, payload, annotation, key, identity } = model;',
          'const { session, payload, annotation, key, identity } = model;\n  const [confirmed, setConfirmed] = useState(false);',
        )
        .replace(
          press,
          'if (confirming && !confirmed) { setConfirmed(true); return; }\n        if (identity) {\n          void askForReading',
        ),
    );
  }
  browser = await chromium.launch();
  for (const fixture of cases) {
    let board, opened;
    try {
      board = await startIntentBoard({ root });
      const origin = board.react.origin;
      const initial = (await call(origin, 'GET', '/api/data')).body;
      const g = initial.generated;
      const row = initial.sessions.find((row) => row.harness === HARNESS && row.sid === SID);
      assert.ok(row.first_prompt && row.first_prompt_at, 'fixture has no first prompt');
      const script = freshScript();
      script.session = {
        state: fixture.state === 'running' ? 'working' : 'idle',
        ended_at: fixture.state === 'ended' ? g - 30 : null,
        finished_at: null,
        turn_end_at: fixture.state === 'turn-stop' ? g - 30 : null,
        reading_eligibility:
          fixture.state === 'idle' ? { ok: false, reason: 'idle-unknown' } : undefined,
        ...(fixture.noDraft ? { first_prompt: '', instruction: null } : {}),
      };
      script.payload = {
        reading: structuredClone(UNCONSENTED),
        reading_routes: { claude: ROUTE },
        reading_check: 'accepted',
        reading_jobs: {},
      };
      const directions =
        fixture.later || fixture.typed
          ? [
              fact('journey-d1', g - 120, { summary: 'Keep the flag off by default.' }),
              fact('journey-d2', g - 90, {
                summary: 'Write the complete rollback steps before changing anything else.',
              }),
            ]
          : [];
      script.facts = [...directions, ...RECORD(g + 200)];
      const job = {
        id: 'journey-job',
        phase: 'read',
        steps: [{ phase: 'read', text: 'Reading the record' }],
      };
      let saved, readingBody;
      script.routes['/api/reading'] = async (body) => {
        assert.equal(body.allow, true, 'analysis started before Allow');
        assert.equal(body.provider, ROUTE.provider);
        assert.equal(body.words_destination, ROUTE.words_destination);
        assert.equal(body.tool_output, ROUTE.destination);
        readingBody = body;
        if (body.adopt) {
          const reply = await call(origin, 'POST', '/api/annotate', body);
          assert.equal(
            reply.body.persisted,
            true,
            `draft adoption failed: ${JSON.stringify(reply.body)}`,
          );
        }
        saved = (await call(origin, 'GET', '/api/data')).body.sessions.find(
          (row) => row.harness === HARNESS && row.sid === SID,
        );
        assert.ok(
          saved.annotation_goal && saved.annotation_revision,
          'analysis goal was not stored',
        );
        script.payload.reading_jobs = { [`${HARNESS}:${SID}`]: job };
        return { body: { ok: true, job } };
      };
      opened = await openPage(browser, [origin, board.react.viteOrigin], {
        viewport: { width: 1280, height: 900 },
        reducedMotion: 'reduce',
      });
      const { page, context } = opened;
      page.setDefaultTimeout(process.env.CI ? 45000 : 15000);
      await context.addInitScript(countActivations);
      await installScript(context, script);
      await context.route('**/api/direction', async (route) => {
        const body = route.request().postDataJSON();
        const direction = directions.find((entry) => entry.fact_id === body.fact_id);
        assert.ok(direction, 'unlisted direction requested');
        await route.fulfill({
          contentType: 'application/json',
          body: JSON.stringify({
            ok: true,
            text: direction.summary,
            clipped: false,
          }),
        });
      });
      const saves = [];
      await context.route(
        '**/api/annotate',
        quietWhenClosing(async (route) => {
          const body = route.request().postDataJSON();
          saves.push(body);
          const response = await route.fetch();
          if (fixture.state === 'ended' && typeof body.goal === 'string')
            script.session.reading_eligibility = { ok: false, reason: 'revision-after-end' };
          await route.fulfill({ response });
        }),
      );
      await context.route('**/api/stream', (route) =>
        route.fulfill({
          contentType: 'text/event-stream',
          body: ': journey holds the clock\n\n',
        }),
      );
      await page.goto(`${origin}/#n=sessions`);
      const goalLink = page.locator(
        `[data-next-harness="${HARNESS}"][data-next-session="${SID}"] a.next-operation-goal-link`,
      );
      await goalLink.waitFor();
      assert.equal(script.payload.reading.providers[ROUTE.provider], false);
      assert.deepEqual(script.payload.reading.words, {});
      assert.deepEqual(script.payload.reading.tool_output, {});
      assert.deepEqual(await context.cookies(), []);
      assert.deepEqual(
        await page.evaluate(() => globalThis.__journey.initialStorage),
        [],
        'not a first visit',
      );
      await page.evaluate(() => {
        globalThis.__journey.counting = true;
      });
      await goalLink.click();
      await awaitRecordRead(page);
      const goal = page.getByRole('textbox', { name: 'Goal', exact: true });
      await page.waitForFunction(
        (empty) =>
          document.activeElement ===
          document.querySelector(
            empty ? '[data-next-cockpit-held-kind="goal"]' : '#next-session-intent-heading',
          ),
        fixture.noDraft === true,
      );
      assert.equal(await goal.inputValue(), fixture.noDraft ? '' : row.first_prompt);
      await page.evaluate(() => {
        globalThis.__journey.counting = false;
      });
      const howto = page.getByRole('button', { name: 'How Intent and drift works', exact: true });
      await howto.click();
      const popup = page.getByRole('dialog', { name: 'How Intent and drift works', exact: true });
      await popup.waitFor();
      assert.match(await popup.innerText(), /Compass never writes into sessions/);
      await page.keyboard.press('Escape');
      await popup.waitFor({ state: 'hidden' });
      await page.evaluate(() => {
        globalThis.__journey.counting = true;
      });
      const action = (name) => page.getByRole('button', { name, exact: true });
      if (fixture.chosen) {
        const before = await page.evaluate(() => globalThis.__journey.clicks.length);
        await page.getByRole('combobox', { name: 'Use your prompt' }).click();
        await page.getByRole('option').first().click();
        assert.equal(
          await page.evaluate(() => globalThis.__journey.clicks.length),
          before + 2,
          'prompt choice costs one press and one choose',
        );
        assert.match(await page.locator('#next-cockpit-cue-status').innerText(), /Not saved/);
      }
      if (fixture.typed) {
        if (fixture.state === 'ended') {
          assert.match(
            await page.locator('[data-next-ended-goal]').innerText(),
            /Words you save now cannot be read against it/,
          );
          assert.notEqual(await goal.inputValue(), 'Ship the typed queue worker');
        }
        if (!fixture.noDraft) await goal.click();
        else await goal.focus();
        await page.keyboard.press(process.platform === 'darwin' ? 'Meta+a' : 'Control+a');
        await page.keyboard.type('Ship the typed queue worker');
        const before = Date.now() / 1000;
        await action('Save intent').press('Enter');
        await page.waitForFunction(
          () =>
            /Saved as a new revision/.test(
              document.querySelector('.next-cockpit-held-footer')?.textContent || '',
            ) &&
            document
              .querySelector('[data-next-cockpit-action="held-save"]')
              ?.getAttribute('aria-disabled') === 'true',
        );
        const current = (await call(origin, 'GET', '/api/data')).body.sessions.find(
          (row) => row.harness === HARNESS && row.sid === SID,
        );
        assert.ok(
          current.annotation_goal_saved_at >= before,
          'typed save did not set baseline to now',
        );
        assert.equal(saves.length, 1);
        assert.equal(
          await page.locator('.next-cockpit-direction-question').count(),
          0,
          'typed save retained a later direction',
        );
      }
      if (fixture.later) {
        assert.equal(await action('Analyze drift').count(), 0, 'question did not replace Analyze');
        await action('Keep my intent').click();
        for (const direction of directions) {
          const whole = page
            .locator('.next-cockpit-direction-whole-text')
            .filter({ hasText: direction.summary })
            .filter({ visible: true });
          await whole.waitFor();
          assert.equal(await whole.innerText(), direction.summary);
        }
        assert.equal(saves.length, 0, 'first Keep settled before showing every direction whole');
        assert.equal(postsTo(script, '/api/reading').length, 0);
        await action('Keep my intent').press('Enter');
      } else {
        if (fixture.refused) await action('Analyze drift').press('Enter');
        else await action('Analyze drift').click();
      }
      if (fixture.refused) {
        const refusal = page.locator('#next-cockpit-reading-refused');
        assert.match(
          await refusal.innerText(),
          fixture.typed
            ? /saved after this session ended/
            : /Analyze opens while this session runs/,
        );
        assert.equal(await action('Analyze drift').getAttribute('aria-disabled'), 'true');
        assert.equal(
          await page.locator('[data-next-result],.next-cockpit-reading-consent').count(),
          0,
        );
        assert.equal(postsTo(script, '/api/reading').length, 0);
      } else {
        await page.locator('.next-cockpit-reading-consent').waitFor();
        assert.match(
          await page.locator('.next-cockpit-reading-consent').innerText(),
          /Claude Code/,
        );
        assert.equal(postsTo(script, '/api/reading').length, 0, 'consent was skipped');
        // Follow an inserted confirmation so the regression fails on its measured cost, not a missing label.
        if (await action('Confirm analysis').count()) await action('Confirm analysis').click();
        await action('Allow and analyze').press('Enter');
        await page.locator('[data-next-analyzing="journey-job"]').waitFor();
        const readAt = Math.max(Date.now() / 1000, saved.annotation_goal_saved_at || 0);
        const evidenceAt = fixture.typed ? saved.annotation_goal_saved_at : g - 40;
        script.facts = [...directions, ...RECORD(g).map((entry) => ({ ...entry, at: evidenceAt }))];
        const assessment = ASSESSMENT(g, {
          revision_read: saved.annotation_revision,
          revision_read_at: saved.annotation_at,
          window_start: saved.annotation_window_start,
          read_at: readAt,
          evidence_through: readAt,
          goal_source: saved.annotation_goal_source || 'typed',
          goal_source_at: saved.annotation_goal_source_at,
          scope: fixture.state === 'running' ? 'mid-flight' : 'last-turn',
          criteria: {
            goal: {
              result: fixture.noDeparture ? 'consistent with the evidence read' : 'departure',
              cites: [fixture.noDeparture ? 'c2' : 'c1'],
              detail: fixture.noDeparture
                ? 'The recorded check passed.'
                : 'It stopped running the tests.',
              clause: saved.annotation_goal,
            },
          },
        });
        script.session.annotation_assessment = assessment;
        script.session.annotation_reading_count = 1;
        // A completed synthetic job publishes a new board clock, just as a real collection does.
        script.payload.generated = readAt + 1;
        script.payload.reading_jobs = {};
        script.payload.reading = {
          providers: { claude: true },
          words: { claude: true },
          tool_output: { claude: ['api'] },
          used: 1,
          limit: 10,
        };
        script.work.analysis_levels = [
          {
            harness: HARNESS,
            sid: SID,
            revision_read: saved.annotation_revision,
            read_at: readAt,
            level: 'not_enough',
            reasons: ['no-outcome-line'],
            cites: [fixture.noDeparture ? 'c2' : 'c1'],
          },
        ];
        await page.evaluate(() =>
          globalThis.dispatchEvent(
            new StorageEvent('storage', {
              key: 'compass.next.revision',
              newValue: '9999999999.journey',
            }),
          ),
        );
        await page.locator('[data-next-result]').waitFor();
        await page.getByText('Not enough recorded yet', { exact: true }).first().waitFor();
        if (fixture.noDeparture) {
          const finding = page.locator('[data-next-result-goal] .next-cockpit-reading-result');
          assert.match(await finding.innerText(), /Consistent with #2/);
          const evidence = page.locator('[data-next-entry-id="c2"]');
          await evidence.scrollIntoViewIfNeeded();
          assert.match(await evidence.innerText(), /pytest/);
          assert.equal(await evidence.isVisible(), true, 'cited record requires another press');
          assert.equal(await page.locator('[data-next-result-state="departure"]').count(), 0);
        } else {
          const account = page.locator('[data-next-result] .next-cockpit-assessment-account');
          assert.equal(await account.isVisible(), true, 'finding requires another press');
          assert.match(await account.innerText(), /It stopped running the tests/);
          const evidence = account.locator('.next-cockpit-assessment-evidence');
          assert.equal(await evidence.isVisible(), true, 'evidence requires another press');
          assert.match(await evidence.innerText(), /pytest -q/);
          assert.match(await evidence.innerText(), /\d{4}-\d\d-\d\d \d\d:\d\d:\d\d UTC/);
        }
        assert.equal(postsTo(script, '/api/reading').length, 1);
        assert.ok(readingBody);
      }
      const clicks = await page.evaluate(() => globalThis.__journey.clicks);
      receipts.push({
        fixture: fixture.name,
        clicks: clicks.length,
        budget: fixture.budget,
        path: clicks,
      });
      console.log(`${fixture.name}: ${clicks.length}/${fixture.budget} clicks`);
      assert.ok(
        clicks.length <= fixture.budget,
        `${fixture.name}: ${clicks.length} clicks exceed budget ${fixture.budget}: ${clicks.join(' > ')}`,
      );
      assert.equal(clicks.filter((name) => name === 'Save intent').length, fixture.typed ? 1 : 0);
      assert.deepEqual(opened.log.externalRequests, []);
      assert.deepEqual(opened.log.pageErrors, []);
      assert.deepEqual(opened.log.consoleErrors, []);
    } finally {
      await opened?.close();
      await board?.close();
    }
  }
} finally {
  console.log(JSON.stringify({ mutation: mutation || null, receipts }, null, 2));
  await browser?.close();
  await rm(root, { recursive: true, force: true });
}
