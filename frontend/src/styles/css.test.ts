import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { resolve } from 'node:path';
import { build } from 'vite';
import { beforeAll, describe, expect, it } from 'vitest';

// Compile the actual entry in memory: no packaged page or integrity receipt is rewritten.
let css = '';
beforeAll(async () => {
  const result = await build({
    configFile: resolve('frontend/vite.config.mts'),
    logLevel: 'silent',
    build: { write: false },
  });
  const outputs = Array.isArray(result) ? result : [result];
  for (const output of outputs) {
    if (!('output' in output)) throw new Error('Expected a completed CSS build');
    for (const asset of output.output)
      if (asset.type === 'asset' && asset.fileName.endsWith('.css')) css += String(asset.source);
  }
  expect(css.length).toBeGreaterThan(1000);
}, 30_000);

const clean = (text: string) => text.replace(/\/\*[\s\S]*?\*\//g, '');
export function externalUrls(text: string): string[] {
  return [...clean(text).matchAll(/url\(\s*([^)]*)\)/g)]
    .map((match) =>
      (match[1] ?? '')
        .trim()
        .replace(/^(["\x27])(.*)\1$/s, '$2')
        .trim(),
    )
    .filter((value) => !value.startsWith('data:') && !value.startsWith('#'));
}

const REM = /^(?:[0-9]+(?:\.[0-9]+)?|\.[0-9]+)rem$/;
const STEPS = { label: 0.8125, body: 0.9375, value: 1.125, head: 1.5, hero: 2.125 };
const PALETTE = {
  sunk: '#eef1f4',
  bg: '#f4f6f8',
  panel: '#ffffff',
  raise: '#fafbfc',
  line: '#7b8794',
  'line-hi': '#52606d',
  rule: '#e3e7eb',
  ink: '#1f2933',
  ink2: '#52606d',
  ink3: '#5c6976',
  'ink-label': 'var(--ink2)',
  'ink-value': 'var(--ink)',
  'ink-absence': 'var(--ink2)',
  'ink-caption': 'var(--ink2)',
  accent: '#2f7d5b',
  'accent-dim': '#21573f',
  'on-accent': '#ffffff',
  cite: '#1d4ed8',
  amber: '#92400e',
  clay: '#9a3412',
  'status-working-bg': '#e8f0fe',
  'status-working-ink': '#1d4ed8',
  'status-waiting-bg': '#fef3e2',
  'status-waiting-ink': '#92400e',
  'status-quiet-bg': '#eef1f4',
  'status-quiet-ink': '#3e4c59',
  'status-ended-bg': '#e6f2ec',
  'status-ended-ink': '#21573f',
  'progress-on-track': '#2f7d5b',
  'progress-slightly-off-course': '#c2410c',
  'progress-off-course': '#c2410c',
  'progress-way-off-course': '#7c2d12',
  'worth-a-look': 'var(--progress-off-course)',
  'destructive-solid': '#9a3412',
  scrim: 'rgb(31 41 51 / 40%)',
  'e-raise': '0 1px 2px rgb(31 41 51 / 12%)',
  'e-pop': '0 8px 24px rgb(31 41 51 / 18%)',
  'e-dialog': '0 16px 48px rgb(31 41 51 / 24%)',
  hatch: 'repeating-linear-gradient(135deg, transparent 0 5px, rgb(31 41 51 / 9%) 5px 6px)',
};
// The production optimizer shortens opaque white and serializes these alpha colours as hex.
const COMPILED_PALETTE = {
  ...PALETTE,
  panel: '#fff',
  'on-accent': '#fff',
  scrim: '#1f293366',
  'e-raise': '0 1px 2px #1f29331f',
  'e-pop': '0 8px 24px #1f29332e',
  'e-dialog': '0 16px 48px #1f29333d',
  hatch: 'repeating-linear-gradient(135deg, transparent 0 5px, #1f293317 5px 6px)',
};
const source = (path: string) =>
  clean(readFileSync(new URL(`../${path}`, import.meta.url), 'utf8'));
const theme = source('styles/tailwind.css');
const paletteBlock = /@theme static\s*\{[^}]+\}/;
const hexColour = /#(?:[\da-f]{8}|[\da-f]{6}|[\da-f]{4}|[\da-f]{3})(?![\da-z-])/i;
const tokens = new Map(
  [...(theme.match(paletteBlock)?.[0] ?? '').matchAll(/--([\w-]+):\s*([^;]+);/g)].map(
    ([, name, value]) => [name, value],
  ),
);

function luminance(hex: string): number {
  expect(hex).toMatch(/^#[\da-f]{6}$/i);
  const channels = [1, 3, 5].map((index) => parseInt(hex.slice(index, index + 2), 16) / 255);
  return channels.reduce((total, channel, index) => {
    const linear = channel <= 0.04045 ? channel / 12.92 : ((channel + 0.055) / 1.055) ** 2.4;
    return total + linear * ([0.2126, 0.7152, 0.0722][index] ?? 0);
  }, 0);
}
const cssList: { space(value: string): string[] } = createRequire(import.meta.resolve('vite'))(
  'postcss',
).list;
const FONT_KEYWORDS = new Set([
  'inherit',
  'initial',
  'unset',
  'revert',
  'revert-layer',
  'caption',
  'icon',
  'menu',
  'message-box',
  'small-caption',
  'status-bar',
]);
function fontShorthandSize(value: string): string | undefined {
  if (FONT_KEYWORDS.has(value.toLowerCase())) return undefined;
  const terms = cssList.space(value);
  while (
    /^(?:normal|italic|oblique|small-caps|bold|bolder|lighter|[1-9]\d{0,2}|1000)$/i.test(
      terms[0] ?? '',
    )
  ) {
    const term = terms.shift();
    if (
      term?.toLowerCase() === 'oblique' &&
      /^[+-]?(?:\d+(?:\.\d+)?|\.\d+)(?:deg|grad|rad|turn)$/i.test(terms[0] ?? '')
    )
      terms.shift();
  }
  return terms[0]?.split('/')[0] ?? value;
}
export function builtProblems(input: string): string[] {
  const text = clean(input);
  const problems: string[] = [];
  const properties = new Map<string, string>();
  const paletteDeclarations = new Map(Object.keys(PALETTE).map((name) => [`--${name}`, 0]));
  for (const [, name, value] of text.matchAll(/(--[\w-]+)\s*:\s*([^;}]+)/g)) {
    if (name === undefined || value === undefined) continue;
    properties.set(name, value.trim());
    const count = paletteDeclarations.get(name);
    if (count !== undefined) paletteDeclarations.set(name, count + 1);
  }
  // The ruled value must be the sole declaration so no other rule can override it.
  for (const [token, expected] of Object.entries(COMPILED_PALETTE)) {
    const name = `--${token}`;
    if (paletteDeclarations.get(name) !== 1 || properties.get(name) !== expected)
      problems.push(`palette declaration ${name}`);
  }
  for (const match of text.matchAll(
    /@property\s+(--[\w-]+)\s*\{[^}]*initial-value\s*:\s*([^;}]+)/g,
  ))
    if (!properties.has(match[1] as string))
      properties.set(match[1] as string, (match[2] ?? '').trim());
  const resolveValue = (value: string, seen = new Set<string>()): string =>
    value.replace(
      /var\(\s*(--[\w-]+)\s*(?:,\s*([^()]*))?\)/g,
      (_whole, name: string, fallback?: string) => {
        if (seen.has(name)) {
          problems.push(`cyclic variable ${name}`);
          return '';
        }
        const next = properties.get(name) ?? fallback;
        if (next === undefined) {
          problems.push(`undeclared variable ${name}`);
          return '';
        }
        return resolveValue(next, new Set([...seen, name]));
      },
    );
  // Follow references in declarations as well as in font sizes; a declared alias can still be broken.
  resolveValue(text);
  if (/@import\b/.test(text)) problems.push('remaining import');
  if (externalUrls(text).length || /https?:\/\//.test(text)) problems.push('external asset');
  if (
    /prefers-color-scheme/.test(text) ||
    !/color-scheme\s*:\s*light(?:[;}])/.test(text) ||
    /color-scheme\s*:\s*(?!light(?:[;}]))[^;}]+/.test(text)
  )
    problems.push('light scheme');
  if (/--ctl-/.test(text)) problems.push('retired control alias');
  for (const [name, value] of Object.entries(STEPS))
    if (
      Number.parseFloat(properties.get(`--fs-${name}`) ?? '') !== value ||
      !REM.test(properties.get(`--fs-${name}`) ?? '') ||
      !properties.get(`--fs-${name}`)?.endsWith('rem')
    )
      problems.push(`type step ${name}`);
  const steps = [...properties.keys()].filter((name) => name.startsWith('--fs-')).sort();
  if (
    steps.join(',') !==
    Object.keys(STEPS)
      .map((name) => `--fs-${name}`)
      .sort()
      .join(',')
  )
    problems.push('type step inventory');
  for (const match of text.matchAll(/(?<![-\w])(font-size|font)\s*:\s*([^;}]+)/g)) {
    const declaration = resolveValue((match[2] ?? '').trim().replace(/\s*!important$/, ''));
    const value = match[1] === 'font' ? fontShorthandSize(declaration) : declaration;
    if (value === undefined) continue;
    if (
      !['inherit', '100%', '0'].includes(value) &&
      !(REM.test(value) && Object.values(STEPS).includes(Number.parseFloat(value)))
    )
      problems.push(`off-scale size ${value}`);
  }
  if (!/body\{[^}]*font-size\s*:\s*var\(--fs-body\)/.test(text)) problems.push('body type');
  if (properties.get('--ink-absence') !== 'var(--ink2)') problems.push('absence ink');
  return [...new Set(problems)].sort();
}

describe('the light board palette', () => {
  it.each([
    ['--bg', ':root { --bg: rgb(20 20 15); }'],
    ['--ink-caption', ':root { --ink-caption: rgb(205 199 180) !important; }'],
  ])('rejects a compiled override of %s', (name, override) => {
    expect(builtProblems(css + override)).toContain(`palette declaration ${name}`);
  });

  it('recognizes hex colours followed by a Tailwind underscore separator', () => {
    expect('[box-shadow:#000_0_18px_44px_-22px]').toMatch(hexColour);
  });

  it.each(Object.entries(PALETTE))('keeps the ruled --%s token', (name, value) => {
    expect(tokens.get(name)).toBe(value);
  });

  it.each(['panel', 'bg'])('makes control boundaries visible on --%s at 3:1 or more', (surface) => {
    const backgrounds = [luminance(tokens.get(surface) ?? ''), luminance(tokens.get('line') ?? '')];
    expect(
      (Math.max(...backgrounds) + 0.05) / (Math.min(...backgrounds) + 0.05),
    ).toBeGreaterThanOrEqual(3);
  });

  it('uses the 13px type step for badges and the 12px radius for session status tiles', () => {
    const badge = source('ui/badge.tsx');
    for (const variant of ['status', 'progress', "'count-chip'"]) {
      expect(badge).toMatch(new RegExp(`${variant}:\\s*'[^']*\\btext-label\\b`));
    }
    expect(css).toMatch(/--fs-label:\s*\.8125rem/);
    expect(css).toContain('.rounded-status-tile');
    expect(theme).toContain('--radius-status-tile: var(--sp-3);');
    expect(theme).toContain('--sp-3: 0.75rem;');
  });

  it('uses the on-accent token for primary foregrounds', () => {
    expect(theme).toMatch(/--color-primary-foreground:\s*var\(--on-accent\);/);
  });

  it.each([
    ['styles/tailwind.css', theme.replace(paletteBlock, '')],
    ...[
      'shell/favicon.ts',
      'terminal/owner.ts',
      'controls/gallery.tsx',
      'drift/CitationLink.tsx',
      'ui/button.tsx',
      'ui/tooltip.tsx',
      'ui/popover.tsx',
      'ui/select.tsx',
    ].map((path) => [path, source(path)]),
  ])('keeps hard-coded hex colours out of %s', (_path, text) => {
    expect(text).not.toMatch(hexColour);
  });
});

describe('the compiled stylesheet', () => {
  it('keeps local assets, a light scheme, resolved variables and the five type steps', () => {
    expect(builtProblems(css)).toEqual([]);
  });
  it('detects quoted external URLs', () => {
    expect(externalUrls('.a{background:url("https://x.test/a.png")} ')).toEqual([
      'https://x.test/a.png',
    ]);
    expect(externalUrls('.a{background:url(data:image/svg+xml;base64,AA==)}')).toEqual([]);
  });
  it.each([
    ['type step', /--fs-label:[^;}]+/, '--fs-label:.75rem', 'type step label'],
    ['body type', /body\{([^}]*?)font-size:var\(--fs-body\);?/, 'body{$1', 'body type'],
    ['colour', /--ink-absence:[^;}]+/, '--ink-absence:var(--missing-ink)', 'absence ink'],
    ['light scheme', /color-scheme:light/, 'color-scheme:dark', 'light scheme'],
    ['variable', /--ink2:[^;}]+/, '--ink2:var(--missing-ink)', 'undeclared variable --missing-ink'],
  ] as const)('fails a mutation removing %s', (_name, needle, replacement, reason) => {
    expect(css).toMatch(needle);
    expect(builtProblems(css.replace(needle, replacement))).toContain(reason);
  });
  it.each([
    ['.dead{--fs-extra:.75rem}', 'type step inventory'],
    ['.dead{font-size:12px}', 'off-scale size 12px'],
    ['.dead{font:12px var(--sans)}', 'off-scale size 12px'],
    ['.dead{font:italic small-caps 600 12px/1.5 var(--sans)}', 'off-scale size 12px'],
    ['.dead{--bad-size:12px;font:var(--bad-size) var(--sans)}', 'off-scale size 12px'],
    ['.dead{color:var(--missing)}', 'undeclared variable --missing'],
    ['.dead{background:url(https://x.test/a.png)}', 'external asset'],
    ['@import url("a.css");', 'remaining import'],
    ['@media(prefers-color-scheme:dark){.dead{color:white}}', 'light scheme'],
    ['.dead{--a:var(--b);--b:var(--a);color:var(--a)}', 'cyclic variable --a'],
  ])('fails a compiled addition %s', (addition, reason) => {
    expect(builtProblems(css + addition)).toContain(reason);
  });
  it.each([
    '.dead{font:.8125rem var(--sans)}',
    '.dead{font:italic small-caps 600 .9375rem/1.5 "A Font",sans-serif}',
    '.dead{font:normal 1.125rem / 1.5 var(--sans)}',
    '.dead{font:oblique 10deg bold 1.5rem var(--sans)}',
    '.dead{font:2.125rem var(--sans)!important}',
    ...['label', 'body', 'value', 'head', 'hero'].map(
      (step) => `.dead{font:500 var(--fs-${step})/1.55 var(--sans)}`,
    ),
    '.dead{--font:italic var(--fs-body)/1.5 var(--sans);font:var(--font)}',
    ...[
      'inherit',
      'initial',
      'unset',
      'revert',
      'revert-layer',
      'caption',
      'icon',
      'menu',
      'message-box',
      'small-caption',
      'status-bar',
    ].map((keyword) => `.dead{font:${keyword}}`),
  ])('accepts an on-scale or system font shorthand %s', (addition) => {
    expect(builtProblems(css + addition)).toEqual([]);
  });
});
