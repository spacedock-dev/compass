import { createRequire } from 'node:module';
import { mkdir, readFile, readdir, writeFile } from 'node:fs/promises';
import { resolve } from 'node:path';
import { gunzipSync } from 'node:zlib';
import { fileURLToPath } from 'node:url';

// Use the parser Vite itself bundles under the pinned lockfile.
const postcss = createRequire(import.meta.resolve('vite'))('postcss');
export const selectorKey = (selector) =>
  selector
    .replaceAll("'", '"')
    .replace(/\s*([>+~,=])\s*/g, '$1')
    .replace(/\s+/g, ' ')
    .trim();
export const selectors = (selector) => postcss.list.comma(selector).map(selectorKey);
const ruleContext = (rule) => {
  const context = [];
  for (let parent = rule.parent; parent && parent.type !== 'root'; parent = parent.parent)
    if (parent.type === 'atrule' && parent.name !== 'layer')
      context.unshift(`@${parent.name} ${parent.params}`);
  return context.join(' > ');
};
const contextKey = (context) =>
  context
    .replace(/\(max-width:\s*([^)]+)\)/g, '(width<=$1)')
    .replace(/\(min-width:\s*([^)]+)\)/g, '(width>=$1)')
    .replace(/\s+/g, '');
export const coverageKey = (context, selector, declarations) =>
  `${contextKey(context)}|${selectorKey(selector)}|${declarations}`;
const declarationKey = (rule) =>
  rule.nodes
    .filter((node) => node.type === 'decl')
    .map(
      (node) =>
        `${node.prop}:${node.value.replaceAll("'", '"').replace(/\s+/g, '')}${node.important ? '!important' : ''}`,
    )
    .join(';');
export function usedSelectors(entries) {
  const used = new Set();
  for (const entry of entries) {
    const tree = postcss.parse(entry.text);
    tree.walkRules((rule) => {
      if (
        !rule.nodes.some(
          (node) =>
            node.type === 'decl' &&
            entry.ranges.some(
              (range) =>
                // CDP also reports @layer containers as used. Their ranges enclose dead children;
                // only counts inside this style rule may certify one of its declarations.
                range.start >= rule.source.start.offset &&
                range.end <= rule.source.end.offset &&
                range.start < node.source.end.offset &&
                range.end > node.source.start.offset,
            ),
        )
      )
        return;
      for (const selector of selectors(rule.selector))
        used.add(coverageKey(ruleContext(rule), selector, declarationKey(rule)));
    });
  }
  return used;
}
export function sourceRules(text) {
  const rows = [];
  postcss.parse(text).walkRules((rule) => {
    if (!rule.nodes.some((node) => node.type === 'decl')) return;
    rows.push({
      selector: rule.selector,
      context: ruleContext(rule),
      declarations: declarationKey(rule),
      start: rule.source.start.offset,
      end: rule.source.end.offset,
    });
  });
  const groups = new Map();
  for (const row of rows) {
    const key = `${row.context}|${selectorKey(row.selector)}`;
    groups.set(key, [...(groups.get(key) ?? []), row]);
  }
  for (const group of groups.values())
    if (group.length > 1) group.forEach((row, index) => (row.ordinal = index + 1));
  return rows;
}
export function ruleIdentity(file, rule) {
  // Two rules with the same context and selector in one file get an ordinal, so each keeps its own exception.
  const ordinal = rule.ordinal ? `|#${rule.ordinal}` : '';
  return `${file}|${rule.context}|${selectorKey(rule.selector)}${ordinal}`;
}
// Chromium marks a whole style rule used, so one live selector must not certify a dead one in
// the same comma list. Every selector in a list has to be used or pseudo-matched.
const isCovered = (rule, used, pseudo) =>
  selectors(rule.selector).every(
    (key) => used.has(coverageKey(rule.context, key, rule.declarations)) || pseudo.has(key),
  );
export function uncoveredRules(file, text, record) {
  const used = new Set(record.used);
  const pseudo = new Set(record.pseudoMatches);
  return sourceRules(text).filter(
    (rule) => !isCovered(rule, used, pseudo) && !record.exceptions[ruleIdentity(file, rule)],
  );
}
export async function coverageProblems(root, record) {
  const budget = JSON.parse(await readFile(resolve(root, 'frontend/css-budget.json'), 'utf8'));
  const problems = [];
  const identities = new Set();
  const covered = new Set();
  const used = new Set(record.used);
  const pseudo = new Set(record.pseudoMatches);
  const expected = [
    'css-contract',
    'controls-continuity',
    'popover-continuity',
    'sessions-parity',
    'intent-parity',
    'drift-parity',
    'project-parity',
    'console-parity',
    'attention-parity',
    'capacity-parity',
    'terminal-parity',
    'timeline-filter',
    'shell-routing',
    'storage-conformance',
  ];
  for (const mode of ['development', 'production'])
    for (const proof of expected)
      if (!record.runs.includes(`${mode}|${proof}.mjs`))
        problems.push(`Missing coverage: ${mode}/${proof}`);
  for (const file of budget.files) {
    const text = await readFile(resolve(root, file), 'utf8');
    for (const rule of sourceRules(text)) {
      const identity = ruleIdentity(file, rule);
      identities.add(identity);
      if (isCovered(rule, used, pseudo)) covered.add(identity);
    }
    for (const rule of uncoveredRules(file, text, record))
      problems.push(`Uncovered rule: ${ruleIdentity(file, rule)}`);
  }
  for (const [identity, reason] of Object.entries(record.exceptions)) {
    if (!identities.has(identity)) problems.push(`Stale exception: ${identity}`);
    if (covered.has(identity))
      problems.push(`Covered exception: ${identity}; remove it from frontend/css-coverage.json`);
    if (typeof reason !== 'string' || reason.trim().length < 20)
      problems.push(`Missing exception reason: ${identity}`);
  }
  return problems;
}
export async function collect(directory) {
  const used = new Set(),
    pseudoMatches = new Set(),
    runs = new Map();
  let pages = 0,
    sheets = 0;
  for (const file of (await readdir(directory))
    .filter((file) => file.endsWith('.json.gz'))
    .sort()) {
    const run = JSON.parse(gunzipSync(await readFile(resolve(directory, file))));
    runs.set(`${run.mode}|${run.proof.split(/[\\/]/).at(-1)}`, true);
    pages += 1;
    sheets += run.entries.length;
    for (const key of usedSelectors(run.entries)) used.add(key);
    for (const selector of run.pseudoMatches)
      for (const key of selectors(selector)) pseudoMatches.add(key);
  }
  return {
    method:
      'Chromium declaration-range union plus matched pseudo-state bases; anonymous sheets retained with CDP',
    pages,
    sheets,
    runs: [...runs.keys()].sort(),
    used: [...used].sort(),
    pseudoMatches: [...pseudoMatches].sort(),
    exceptions: {},
  };
}

const root = fileURLToPath(new URL('../../', import.meta.url));
if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const [command, argument] = process.argv.slice(2);
  if (command === 'collect') {
    const record = await collect(resolve(argument));
    await mkdir(resolve(root, 'docs/screenshots/css-cleanup'), { recursive: true });
    await writeFile(
      resolve(root, 'docs/screenshots/css-cleanup/coverage.json'),
      JSON.stringify(record, null, 2) + '\n',
    );
    console.log(
      `${record.pages} pages, ${record.sheets} sheets, ${record.used.length} used selectors, ${record.runs.length} proof/mode pairs`,
    );
  } else if (command === 'check') {
    const record = JSON.parse(await readFile(resolve(root, 'frontend/css-coverage.json'), 'utf8'));
    const problems = await coverageProblems(root, record);
    if (problems.length) throw new Error(problems.join('\n'));
    console.log('Every retained hand-written rule is covered or a named exception');
  } else throw new Error('usage: css-coverage.mjs collect DIRECTORY | check');
}
