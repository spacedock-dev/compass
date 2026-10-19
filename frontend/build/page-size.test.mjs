import assert from 'node:assert/strict';
import { readFile, stat } from 'node:fs/promises';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';

/* The sample fixture ships inside the page, so a longer sample makes every page load larger.
   docs/design-sample-session.md#how-big-it-may-be owns both bounds and why; raise either only there. */
const PAGE_MAX_BYTES = 1_884_747 + 400 * 1024;
const FIXTURE_MAX_BYTES = 250_000;

const root = new URL('../../', import.meta.url);
const page = new URL('compass/skills/compass/compass_runtime/web/react.html', root);
const fixture = new URL('frontend/src/sample/session.fixture.json', root);

test('the built page stays within its byte bound', async () => {
  const { size } = await stat(fileURLToPath(page));
  assert.ok(
    size <= PAGE_MAX_BYTES,
    `react.html is ${String(size)} bytes, over the ${String(PAGE_MAX_BYTES)}-byte bound`,
  );
});

test('the sample fixture stays within its byte bound', async () => {
  const compact = JSON.stringify(JSON.parse(await readFile(fileURLToPath(fixture), 'utf8')));
  const size = Buffer.byteLength(compact, 'utf8');
  assert.ok(
    size <= FIXTURE_MAX_BYTES,
    `the sample fixture is ${String(size)} compact bytes, over the ${String(FIXTURE_MAX_BYTES)}-byte bound`,
  );
});
