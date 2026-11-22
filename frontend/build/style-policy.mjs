import { readFile, readdir } from 'node:fs/promises';
import { join, resolve, relative } from 'node:path';
import { fileURLToPath } from 'node:url';
import { execFileSync } from 'node:child_process';
import { isDeepStrictEqual } from 'node:util';
import { loadCsf } from 'storybook/internal/csf-tools';
import ts from 'typescript';
import { __unstable__loadDesignSystem } from 'tailwindcss';

const utilityTypes = await __unstable__loadDesignSystem('@theme { --spacing: 0.25rem; }');

const ROOT = fileURLToPath(new URL('../../', import.meta.url));
const RECORD = 'frontend/css-budget.json';
const FIRST_LAYER = 'frontend/first-layer-budget.json';
const RULE =
  'UTF-8 bytes after CRLF to LF normalization, including comments, of all CSS under frontend except the directive-only Tailwind entry. Strip only an outer @layer legacy wrapper. Inventory every path; added paths need prior base approval.';
const slashed = (path) => path.replaceAll('\\', '/');
export const cssBytes = (text) =>
  Buffer.byteLength(
    text.replaceAll('\r\n', '\n').replace(/^@layer legacy \{\n([\s\S]*)\}\n$/, '$1'),
  );
async function files(root, directory) {
  const found = [];
  for (const item of await readdir(join(root, directory), { withFileTypes: true })) {
    const path = `${directory}/${item.name}`;
    if (item.isDirectory()) found.push(...(await files(root, path)));
    else if (item.isFile()) found.push(path);
    else throw new Error(`Unsupported source entry ${path}`);
  }
  return found.sort();
}

function walkSource(source, file, inspect) {
  const tree = ts.createSourceFile(file, source, ts.ScriptTarget.Latest, true);
  const visit = (node) => {
    inspect(node, tree);
    ts.forEachChild(node, visit);
  };
  visit(tree);
}

function scanUtilities(source, file, inspect) {
  // Scan strings, including cva recipes and conditional classes, rather than className alone.
  walkSource(source, file, (node) => {
    if (
      ts.isStringLiteralLike(node) ||
      ts.isTemplateHead(node) ||
      ts.isTemplateMiddle(node) ||
      ts.isTemplateTail(node)
    ) {
      for (const token of node.text.split(/\s+/)) {
        const utility = token
          .split(/:(?![^[]*\])(?![^(]*\))/)
          .at(-1)
          .replace(/^!/, '')
          .replace(/!$/, '');
        inspect(utility, token);
      }
    }
  });
}

export function scaleProblems(source, file = 'source.tsx') {
  const found = new Set();
  scanUtilities(source, file, (utility, token) => {
    if (
      /^text-(?:xs|sm|base|lg|xl|[2-9]xl)(?:\/.*)?$/.test(utility) ||
      // Tailwind resolves unhinted variables (including [--x]) as color. Let its pinned
      // compiler distinguish colors from signed lengths, keywords, math and size hints.
      (/^text-(?:\[|\()/.test(utility) &&
        utilityTypes.candidatesToCss([utility]).some((css) => /\bfont-size:/.test(css || ''))) ||
      /^(?:text|font)-\(length:/.test(utility) ||
      /^\[font-size:/.test(utility) ||
      /^rounded(?:-[trblse]{1,2})?-(?:xs|sm|md|lg|xl|[2-4]xl)$/.test(utility) ||
      /^(?:bg|text|border|ring|fill|stroke|shadow|outline|decoration|accent|caret|divide|from|via|to)-(?:slate|gray|zinc|neutral|stone|red|orange|amber|yellow|lime|green|emerald|teal|cyan|sky|blue|indigo|violet|purple|fuchsia|pink|rose)-\d+(?:\/.*)?$/.test(
        utility,
      )
    )
      found.add(token);
  });
  return [...found].sort();
}

const sourceModule = (file) =>
  file.startsWith('frontend/src/') && /\.[cm]?[jt]sx?$/.test(file) && !/\.test\./.test(file);
const styleSource = (file) => sourceModule(file) || file.endsWith('.css');
const storySource = (file) => file.startsWith('frontend/stories/') && file.endsWith('.stories.tsx');

export function firstLayerTokens(source, file) {
  const found = {};
  const add = (kind, token) => {
    found[kind] ??= [];
    found[kind].push(token);
  };
  if (file.endsWith('.css')) {
    const css = source.replace(/\/\*[\s\S]*?\*\//g, '');
    const declarations = [
      ['monospace', 'font-family: var(--mono)', /[;{]\s*font-family\s*:\s*var\(\s*--mono\s*\)/gi],
      ['uppercase', 'text-transform: uppercase', /[;{]\s*text-transform\s*:\s*uppercase\b/gi],
      ['tracking', 'letter-spacing', /[;{]\s*letter-spacing\s*:/gi],
    ];
    for (const [kind, token, pattern] of declarations)
      for (const _match of css.matchAll(pattern)) add(kind, token);
  } else {
    scanUtilities(source, file, (utility, token) => {
      if (utility === 'uppercase' || utility === '[text-transform:uppercase]')
        add('uppercase', token);
      if (/^(?:-?tracking-|\[letter-spacing:)/.test(utility)) add('tracking', token);
      if (
        utility === 'font-mono' ||
        /^(?:\[font-family:|font-\[(?:family-name:)?)var\(--mono\)\]$/.test(utility)
      )
        add('monospace', token);
    });
  }
  return found;
}

export function inlineSvgProblems(source, file) {
  const problems = new Set();
  if (file.startsWith('frontend/src/ui/')) return [];
  walkSource(source, file, (node, tree) => {
    if (
      (ts.isJsxOpeningElement(node) || ts.isJsxSelfClosingElement(node)) &&
      node.tagName.getText(tree) === 'svg'
    ) {
      const { line } = tree.getLineAndCharacterOfPosition(node.getStart(tree));
      problems.add(`${file}:${line + 1}: inline <svg> belongs in frontend/src/ui/`);
    }
  });
  return [...problems];
}

const countTokens = (tokensByFile) =>
  Object.fromEntries(
    Object.entries(tokensByFile)
      .filter(([, tokens]) => Object.keys(tokens).length)
      .map(([file, tokens]) => [
        file,
        Object.fromEntries(Object.entries(tokens).map(([kind, hits]) => [kind, hits.length])),
      ]),
  );

function storyIds(source, fileName) {
  return loadCsf(source, { fileName, makeTitle: (title) => title })
    .parse()
    .indexInputs.map(({ __id }) => __id);
}

export function bootstrapFirstLayer(paths, readBase) {
  return {
    counts: countTokens(
      Object.fromEntries(
        paths.filter(styleSource).map((file) => [file, firstLayerTokens(readBase(file), file)]),
      ),
    ),
  };
}

export function compareFirstLayer(tokensByFile, record, base) {
  const problems = [];
  for (const [file, tokens] of Object.entries(tokensByFile)) {
    for (const [kind, hits] of Object.entries(tokens)) {
      const previous = base.counts[file]?.[kind] ?? 0;
      if (
        hits.length <= previous ||
        (kind === 'monospace' && Object.hasOwn(record.technical, file))
      )
        continue;
      const names = [...new Set(hits)].join(', ');
      problems.push(`${file}: first-layer ${kind} rose ${previous} -> ${hits.length} (${names})`);
    }
  }
  // The first record seeds the measured exemptions for the legacy views already on the stack.
  const priorStories = base.stories && new Set(base.stories);
  for (const id of record.stories) {
    if (priorStories && !priorStories.has(id))
      problems.push(`Story audit exemption added against the PR base: ${id}`);
  }
  return problems;
}

export async function unusedUi(root) {
  const source = await files(root, 'frontend/src');
  const modules = new Set(
    source.filter((file) => /\.[cm]?[jt]sx?$/.test(file) && !/\.test\./.test(file)),
  );
  const visited = new Set();
  async function walk(file) {
    if (visited.has(file)) return;
    visited.add(file);
    const tree = ts.createSourceFile(
      file,
      await readFile(join(root, file), 'utf8'),
      ts.ScriptTarget.Latest,
      true,
    );
    const importedFiles = new Set();
    const visit = (node) => {
      if (ts.isImportDeclaration(node) || ts.isExportDeclaration(node)) {
        const clause = ts.isImportDeclaration(node) ? node.importClause : node;
        const bindings = ts.isImportDeclaration(node) ? clause?.namedBindings : node.exportClause;
        const named = bindings && (ts.isNamedImports(bindings) || ts.isNamedExports(bindings));
        const onlyTypes =
          clause?.isTypeOnly ||
          (named &&
            !clause.name &&
            bindings.elements.length > 0 &&
            bindings.elements.every((item) => item.isTypeOnly));
        if (!onlyTypes && node.moduleSpecifier && ts.isStringLiteral(node.moduleSpecifier))
          importedFiles.add(node.moduleSpecifier.text);
      } else if (
        ts.isCallExpression(node) &&
        node.expression.kind === ts.SyntaxKind.ImportKeyword &&
        node.arguments[0] &&
        ts.isStringLiteralLike(node.arguments[0])
      ) {
        importedFiles.add(node.arguments[0].text);
      }
      ts.forEachChild(node, visit);
    };
    visit(tree);
    for (const fileName of importedFiles) {
      if (!fileName.startsWith('.') && !fileName.startsWith('@/')) continue;
      const base = fileName.startsWith('@/')
        ? `frontend/src/${fileName.slice(2)}`
        : slashed(relative(root, resolve(root, file, '..', fileName)));
      const target = [
        base,
        ...['.ts', '.tsx', '.js', '.jsx', '/index.ts', '/index.tsx'].map((suffix) => base + suffix),
      ].find((candidate) => modules.has(candidate));
      if (target) await walk(target);
    }
  }
  await walk('frontend/src/main.tsx');
  return [...modules]
    .filter((file) => file.startsWith('frontend/src/ui/') && !visited.has(file))
    .sort();
}

export function compareBase(record, base) {
  const problems = [];
  if (record.bytes > base.bytes)
    problems.push(`Hand-written CSS allowance rose: ${base.bytes} -> ${record.bytes}`);
  if (record.rule !== base.rule || record.files.some((file) => !base.files.includes(file)))
    problems.push('CSS counting rule or paths changed against the PR base');
  return problems;
}

export async function checkStyles(root = ROOT, base) {
  const record = JSON.parse(await readFile(join(root, RECORD), 'utf8'));
  const frontend = await files(root, 'frontend');
  const source = frontend.filter(sourceModule);
  const css = frontend.filter(
    (file) => file.endsWith('.css') && file !== 'frontend/src/styles/tailwind.css',
  );
  const problems = [];
  const firstLayer = JSON.parse(await readFile(join(root, FIRST_LAYER), 'utf8'));
  const tokensByFile = {};
  for (const path of frontend.filter(styleSource)) {
    tokensByFile[path] = firstLayerTokens(await readFile(join(root, path), 'utf8'), path);
  }
  const actual = countTokens(tokensByFile);
  for (const path of new Set([...Object.keys(actual), ...Object.keys(firstLayer.counts)])) {
    if (!isDeepStrictEqual(actual[path], firstLayer.counts[path])) {
      const hits = Object.values(tokensByFile[path] ?? {}).flat();
      problems.push(
        `${path}: first-layer count differs from the record (${[...new Set(hits)].join(', ') || 'no tokens'})`,
      );
    }
  }
  for (const [path, reason] of Object.entries(firstLayer.technical)) {
    if (!Object.hasOwn(tokensByFile, path) || !reason.trim() || reason.includes('\n'))
      problems.push(`${path}: technical allowance requires a source file and a one-line reason`);
  }
  const storyInventory = new Set();
  for (const path of frontend.filter(storySource)) {
    for (const id of storyIds(await readFile(join(root, path), 'utf8'), path))
      storyInventory.add(id);
  }
  for (const id of firstLayer.stories) {
    if (!storyInventory.has(id)) problems.push(`Unknown story audit exemption: ${id}`);
  }
  if (record.rule !== RULE) problems.push('CSS counting rule differs from the gate');
  if (JSON.stringify(css) !== JSON.stringify(record.files))
    problems.push('CSS files differ from the counted paths');
  let bytes = 0;
  for (const file of css) bytes += cssBytes(await readFile(join(root, file), 'utf8'));
  if (bytes !== record.bytes)
    problems.push(`Hand-written CSS bytes differ: record ${record.bytes}, actual ${bytes}`);
  for (const file of source) {
    const text = await readFile(join(root, file), 'utf8');
    problems.push(...inlineSvgProblems(text, file));
    if (/\.tsx?$/.test(file)) {
      for (const token of scaleProblems(text, file))
        problems.push(`${file}: forbidden scale class ${token}`);
    }
  }
  for (const file of await unusedUi(root))
    problems.push(`${file}: no importer reachable from the shipped entry`);
  // The only excluded sheet is the toolchain entry. Ordinary rules cannot be hidden there.
  const entry = (await readFile(join(root, 'frontend/src/styles/tailwind.css'), 'utf8')).replace(
    /\/\*[\s\S]*?\*\//g,
    '',
  );
  const directives = entry
    .replace(/@theme(?:\s+static)?\s*\{[^{}]*\}/g, '')
    // Variant bodies may wrap the slot in selectors, but cannot carry declarations.
    .replace(
      /@custom-variant\s+data-(?:open|closed)\s*\{\s*(?:@slot;|[^;{}@]+\{\s*@slot;\s*\})\s*\}/g,
      '',
    )
    .replace(/@custom-variant\s+(?:dark|data-open|data-closed)\s+\([^;{}]*\)\s*;/g, '')
    .replace(/@(?:layer|import|source)\s+(?:'[^']*'|"[^"]*"|[^;{}'"])+;/g, '')
    .trim();
  if (directives) problems.push('Tailwind entry contains a rule outside its theme and variants');
  if (base) {
    const git = (...args) =>
      execFileSync('git', args, { cwd: root, encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'] });
    const paths = git('ls-tree', '-r', '--name-only', base, '--', 'frontend').trim().split('\n');
    // Bootstrap from the base's actual sheets, so introducing the record cannot bless growth.
    const previous = paths.includes(RECORD)
      ? JSON.parse(git('show', `${base}:${RECORD}`))
      : {
          rule: RULE,
          files: paths
            .filter((file) => file.endsWith('.css') && file !== 'frontend/src/styles/tailwind.css')
            .sort(),
        };
    if (previous.bytes === undefined)
      previous.bytes = previous.files.reduce(
        (sum, file) => sum + cssBytes(git('show', `${base}:${file}`)),
        0,
      );
    problems.push(...compareBase(record, previous));
    const readBase = (path) => git('show', `${base}:${path}`);
    const priorLayer = paths.includes(FIRST_LAYER)
      ? JSON.parse(readBase(FIRST_LAYER))
      : bootstrapFirstLayer(paths, readBase);
    problems.push(...compareFirstLayer(tokensByFile, firstLayer, priorLayer));
  }
  return { bytes, problems };
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const args = process.argv.slice(2);
  if (args.length && (args.length !== 2 || args[0] !== '--base'))
    throw new Error('usage: node frontend/build/style-policy.mjs [--base SHA]');
  try {
    const result = await checkStyles(ROOT, args[1] || process.env.PR_BASE);
    console.log(`Hand-written CSS: ${result.bytes} bytes`);
    for (const problem of result.problems) console.error(problem);
    process.exitCode = result.problems.length ? 1 : 0;
  } catch (error) {
    console.error(error.message);
    process.exitCode = 1;
  }
}
