import { mkdir, mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import assert from 'node:assert/strict';
import { test } from 'node:test';
import {
  usedSelectors,
  uncoveredRules,
  ruleIdentity,
  sourceRules,
  coverageProblems,
} from './css-coverage.mjs';

test('a declaration used in any world retains the whole rule', () => {
  const text = '.a { color: red; padding: 8px } .b { color: blue }';
  const used = [...usedSelectors([{ text, ranges: [{ start: 6, end: 16 }] }])];
  assert.deepEqual(used, ['|.a|color:red;padding:8px']);
  const record = { used, pseudoMatches: [], exceptions: {} };
  assert.deepEqual(
    uncoveredRules('sheet.css', text, record).map((rule) => rule.selector),
    ['.b'],
  );
});
test('adding a dead rule fails even when the rest of the sheet is covered', () => {
  const record = { used: ['|.a|color:red'], pseudoMatches: [], exceptions: {} };
  assert.deepEqual(uncoveredRules('sheet.css', '.a{color:red}', record), []);
  assert.equal(
    uncoveredRules('sheet.css', '.a{color:red}.dead-mutation{color:red}', record).length,
    1,
  );
});
test('a used cascade-layer container cannot certify its unused children', () => {
  const text = '@layer legacy {.dead{color:red}.used{color:blue}}';
  const start = text.indexOf('.used');
  assert.deepEqual(
    [
      ...usedSelectors([
        {
          text,
          ranges: [
            { start: 7, end: text.length },
            { start, end: text.length - 1 },
          ],
        },
      ]),
    ],
    ['|.used|color:blue'],
  );
});
test('pseudo base matches retain state rules; named exceptions are exact', () => {
  const text = '@media print {.a:hover {color:red}.b {color:blue}}';
  const [first, second] = sourceRules(text);
  const record = {
    used: [],
    pseudoMatches: ['.a:hover'],
    exceptions: { [ruleIdentity('sheet.css', second)]: 'Print output is outside the screen proof' },
  };
  assert.deepEqual(uncoveredRules('sheet.css', text, record), []);
  delete record.exceptions[ruleIdentity('sheet.css', second)];
  assert.deepEqual(uncoveredRules('sheet.css', text, record), [second]);
  assert.equal(first.context, '@media print');
});

for (const [name, used, pseudoMatches, text, identity, covered] of [
  ['used', ['|.a|color:red'], [], '.a{color:red}', 'frontend/sheet.css||.a', true],
  ['pseudo matched', [], ['.a:hover'], '.a:hover{color:red}', 'frontend/sheet.css||.a:hover', true],
  ['unused', [], [], '.a{color:red}', 'frontend/sheet.css||.a', false],
])
  test(`${name} exception ${covered ? 'must be removed' : 'remains valid'}`, async (t) => {
    const repository = fileURLToPath(new URL('../../', import.meta.url));
    const directory = join(repository, 'docs/screenshots');
    await mkdir(directory, { recursive: true });
    const root = await mkdtemp(join(directory, 'css-coverage-fixture-'));
    t.after(() => rm(root, { recursive: true, force: true }));
    await mkdir(join(root, 'frontend'));
    await writeFile(
      join(root, 'frontend/css-budget.json'),
      JSON.stringify({ files: ['frontend/sheet.css'] }),
    );
    await writeFile(join(root, 'frontend/sheet.css'), text);
    const baseline = JSON.parse(
      await readFile(join(repository, 'frontend/css-coverage.json'), 'utf8'),
    );
    const problems = await coverageProblems(root, {
      runs: baseline.runs,
      used,
      pseudoMatches,
      exceptions: { [identity]: 'This state is outside the screen proof fixtures.' },
    });
    if (covered) {
      assert.equal(problems.length, 1);
      assert.match(problems[0], /remove.*frontend\/css-coverage\.json/i);
      assert.ok(problems[0].includes(identity));
    } else assert.deepEqual(problems, []);
  });

test('a dead selector in a used rule comma list is uncovered', () => {
  const record = { used: ['|.a|color:red'], pseudoMatches: [], exceptions: {} };
  assert.deepEqual(uncoveredRules('sheet.css', '.a{color:red}', record), []);
  const [rule] = uncoveredRules('sheet.css', '.a,.dead-piece{color:red}', record);
  assert.equal(rule.selector, '.a,.dead-piece');
});
test('two same-selector rules in one file keep separate exception identities', async (t) => {
  const repository = fileURLToPath(new URL('../../', import.meta.url));
  const directory = join(repository, 'docs/screenshots');
  await mkdir(directory, { recursive: true });
  const root = await mkdtemp(join(directory, 'css-coverage-fixture-'));
  t.after(() => rm(root, { recursive: true, force: true }));
  await mkdir(join(root, 'frontend'));
  await writeFile(
    join(root, 'frontend/css-budget.json'),
    JSON.stringify({ files: ['frontend/sheet.css'] }),
  );
  const text = '.x{color:red}.x{color:blue}';
  await writeFile(join(root, 'frontend/sheet.css'), text);
  const [first, second] = sourceRules(text);
  assert.notEqual(
    ruleIdentity('frontend/sheet.css', first),
    ruleIdentity('frontend/sheet.css', second),
  );
  const baseline = JSON.parse(
    await readFile(join(repository, 'frontend/css-coverage.json'), 'utf8'),
  );
  const record = {
    runs: baseline.runs,
    used: ['|.x|color:red'],
    pseudoMatches: [],
    exceptions: { [ruleIdentity('frontend/sheet.css', first)]: 'Fixture rule kept for identity.' },
  };
  // The exception names the rule that became used; its dead sibling is reported on its own identity.
  const problems = await coverageProblems(root, record);
  assert.equal(problems.length, 2);
  assert.equal(problems[0], `Uncovered rule: ${ruleIdentity('frontend/sheet.css', second)}`);
  assert.match(problems[1], /remove.*frontend\/css-coverage\.json/i);
  assert.ok(problems[1].includes(ruleIdentity('frontend/sheet.css', first)));
  record.exceptions = {
    [ruleIdentity('frontend/sheet.css', second)]: 'Dead fixture rule kept for identity.',
  };
  assert.deepEqual(await coverageProblems(root, record), []);
});
test('a dead selector appended to a covered real rule fails the coverage gate', async () => {
  const file = 'frontend/src/styles/shell.css';
  const root = fileURLToPath(new URL('../../', import.meta.url));
  const record = JSON.parse(
    await readFile(new URL('../css-coverage.json', import.meta.url), 'utf8'),
  );
  const text = await readFile(`${root}${file}`, 'utf8');
  const deadStarts = new Set(uncoveredRules(file, text, record).map((rule) => rule.start));
  const covered = sourceRules(text).find(
    (rule) => !deadStarts.has(rule.start) && !record.exceptions[ruleIdentity(file, rule)],
  );
  assert.ok(covered, 'shell.css has a covered rule to mutate');
  const at = covered.start + text.slice(covered.start).indexOf(covered.selector);
  const mutated = `${text.slice(0, at)}${covered.selector},.next-css-dead-mutation${text.slice(at + covered.selector.length)}`;
  const dead = uncoveredRules(file, mutated, record);
  assert.ok(
    dead.some((rule) => rule.selector.includes('.next-css-dead-mutation')),
    'the appended dead selector is reported',
  );
});
test('the current sheets retain no uncovered rule or unexplained exception', async () => {
  const root = fileURLToPath(new URL('../../', import.meta.url));
  const record = JSON.parse(
    await readFile(new URL('../css-coverage.json', import.meta.url), 'utf8'),
  );
  assert.deepEqual(await coverageProblems(root, record), []);
});

test('a dead duplicate of a real sheet in another budget file fails the coverage gate', async (t) => {
  const repository = fileURLToPath(new URL('../../', import.meta.url));
  const record = JSON.parse(
    await readFile(new URL('../css-coverage.json', import.meta.url), 'utf8'),
  );
  const directory = join(repository, 'docs/screenshots');
  await mkdir(directory, { recursive: true });
  const root = await mkdtemp(join(directory, 'css-coverage-fixture-'));
  t.after(() => rm(root, { recursive: true, force: true }));
  await mkdir(join(root, 'frontend'));
  const text = await readFile(join(repository, 'frontend/src/styles/shell.css'), 'utf8');
  await writeFile(join(root, 'frontend/shell.css'), text);
  await writeFile(join(root, 'frontend/copy.css'), text);
  await writeFile(
    join(root, 'frontend/css-budget.json'),
    JSON.stringify({ files: ['frontend/shell.css', 'frontend/copy.css'] }),
  );
  const problems = await coverageProblems(root, record);
  assert.ok(problems.some((problem) => problem.startsWith('Duplicated rule: frontend/copy.css|')));
  assert.ok(problems.some((problem) => problem.startsWith('Duplicated rule: frontend/shell.css|')));
});
test('a dead-rule mutation added to the current shell fails the coverage gate', async () => {
  const file = 'frontend/src/styles/shell.css';
  const root = fileURLToPath(new URL('../../', import.meta.url));
  const record = JSON.parse(
    await readFile(new URL('../css-coverage.json', import.meta.url), 'utf8'),
  );
  const text = await readFile(`${root}${file}`, 'utf8');
  const dead = uncoveredRules(
    file,
    `${text}\n@layer legacy {.next-css-dead-mutation{color:red}}`,
    record,
  );
  assert.deepEqual(
    dead.map((rule) => rule.selector),
    ['.next-css-dead-mutation'],
  );
});
