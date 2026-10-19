import assert from 'node:assert/strict';
import { readFile, stat } from 'node:fs/promises';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';

/* The sample session's fixture ships inside the built page, so a longer sample makes every install and every
   page load larger. Both numbers were set on 2026-10-19 before the longer sample was built (see the sample
   design record, docs/design-sample-session.md#how-big-it-may-be). The page bound is the page as built then,
   1,884,747 bytes, plus 400 KiB. The page base64-encodes its script, so a fixture byte costs about 4/3 of a
   page byte: the fixture bound of 250,000 compact JSON bytes takes at most about 233 KB of that headroom over
   the first sample's 75,130, and leaves the rest for code. Raise either only by a decision recorded there. */
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
