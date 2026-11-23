import assert from 'node:assert/strict';
import { test } from 'node:test';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { readFile, writeFile, mkdir, mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

const root = fileURLToPath(new URL('../../', import.meta.url));
test('the shipped sources satisfy the style policy', () => {
  const result = spawnSync(process.execPath, ['frontend/build/style-policy.mjs'], {
    cwd: root,
    encoding: 'utf8',
  });
  assert.equal(result.status, 0, result.stderr);
});

test('the scale scan rejects defaults and arbitrary type sizes with variants', async () => {
  const { scaleProblems } = await import('./style-policy.mjs');
  for (const token of [
    'text-sm',
    'hover:text-xl/6',
    'md:text-[14px]',
    'text-[length:var(--other)]',
    'rounded-lg',
    'bg-blue-500',
  ]) {
    assert.deepEqual(scaleProblems(`<div className="${token}" />`), [token]);
  }
  assert.deepEqual(
    scaleProblems(
      `<div className="text-body text-muted-foreground rounded-control text-center" />`,
    ),
    [],
  );
});

test('only components reachable from the shipped entry have importers', async () => {
  const { unusedUi } = await import('./style-policy.mjs');
  const copy = await mkdtemp(join(tmpdir(), 'compass-ui-policy-'));
  try {
    await mkdir(join(copy, 'frontend/src/ui'), { recursive: true });
    await writeFile(
      join(copy, 'frontend/src/main.tsx'),
      'import { Used } from "@/ui/used"; import type { Orphan } from "@/ui/orphan"; Used();',
    );
    await writeFile(
      join(copy, 'frontend/src/ui/used.tsx'),
      'import "./helper"; export const Used = () => null;',
    );
    await writeFile(join(copy, 'frontend/src/ui/helper.ts'), 'export const helper = 1;');
    await writeFile(join(copy, 'frontend/src/ui/orphan.tsx'), 'export const Orphan = () => null;');
    await writeFile(join(copy, 'frontend/src/dead.tsx'), 'import "./ui/orphan";');
    assert.deepEqual(await unusedUi(copy), ['frontend/src/ui/orphan.tsx']);
  } finally {
    await rm(copy, { recursive: true, force: true });
  }
});

test('the PR cannot raise its CSS allowance even when its total matches', async () => {
  const { compareBase } = await import('./style-policy.mjs');
  const record = JSON.parse(await readFile(join(root, 'frontend/css-budget.json'), 'utf8'));
  assert.deepEqual(compareBase(record, record), []);
  assert.match(compareBase({ ...record, bytes: record.bytes + 1 }, record).join('\n'), /rose/);
  assert.match(
    compareBase(record, { ...record, files: record.files.slice(1) }).join('\n'),
    /counting/,
  );
  assert.deepEqual(compareBase({ ...record, bytes: record.bytes - 1 }, record), []);
});

test('the CSS count survives Windows checkout line endings and strips only the outer layer', async () => {
  const { cssBytes } = await import('./style-policy.mjs');
  assert.equal(
    cssBytes('@layer legacy {\r\n.a { color: red; }\r\n}\r\n'),
    Buffer.byteLength('.a { color: red; }\n'),
  );
  assert.equal(cssBytes('.a { color: red; }\n'), Buffer.byteLength('.a { color: red; }\n'));
});

async function policyFixture(run) {
  const copy = await mkdtemp(join(tmpdir(), 'compass-style-policy-'));
  try {
    await mkdir(join(copy, 'frontend/src/styles'), { recursive: true });
    await mkdir(join(copy, 'frontend/src/lib'), { recursive: true });
    await mkdir(join(copy, 'frontend/src/ui'), { recursive: true });
    const record = JSON.parse(await readFile(join(root, 'frontend/css-budget.json'), 'utf8'));
    await writeFile(
      join(copy, 'frontend/css-budget.json'),
      JSON.stringify({ ...record, files: [], bytes: 0 }),
    );
    await writeFile(join(copy, 'frontend/src/main.tsx'), '');
    await writeFile(join(copy, 'frontend/src/styles/tailwind.css'), '');
    await run(copy);
  } finally {
    await rm(copy, { recursive: true, force: true });
  }
}

test('custom variants cannot hide declarations in the excluded Tailwind entry', async () => {
  const { checkStyles } = await import('./style-policy.mjs');
  await policyFixture(async (copy) => {
    const entry = join(copy, 'frontend/src/styles/tailwind.css');
    for (const variant of [
      '@custom-variant data-open { padding: 44px; @slot; }',
      '@custom-variant data-closed { &:where([data-closed]) { padding: 44px; @slot; } }',
      '@custom-variant dark (&:where(.dark)) { padding: 44px; }',
    ]) {
      await writeFile(entry, variant + '\n@source inline("data-open:block");');
      assert.match(
        (await checkStyles(copy)).problems.join('\n'),
        /Tailwind entry contains a rule/,
        variant,
      );
    }
    for (const variant of [
      '@custom-variant dark (&:where(.compass-light-mode, .compass-light-mode *));',
      '@custom-variant data-open (&:where([data-open]));',
      '@custom-variant data-open { @slot; }',
      '@custom-variant data-closed { &:where([data-closed]) { @slot; } }',
    ]) {
      await writeFile(entry, variant);
      assert.deepEqual((await checkStyles(copy)).problems, [], variant);
    }
  });
});

test('the scale gate scans TS recipes and excludes test sources', async () => {
  const { checkStyles } = await import('./style-policy.mjs');
  await policyFixture(async (copy) => {
    for (const path of ['frontend/src/lib/recipe.ts', 'frontend/src/ui/recipe.ts']) {
      await writeFile(
        join(copy, path),
        'export const recipe = <T>(value: T) => { const classes = "text-sm text-[14px]"; return [value, classes]; };',
      );
      if (path.includes('/ui/'))
        await writeFile(join(copy, 'frontend/src/main.tsx'), 'import "./ui/recipe";');
      assert.deepEqual((await checkStyles(copy)).problems, [
        `${path}: forbidden scale class text-[14px]`,
        `${path}: forbidden scale class text-sm`,
      ]);
      await rm(join(copy, path));
    }
    await writeFile(join(copy, 'frontend/src/lib/recipe.test.ts'), 'const recipe = "text-sm";');
    assert.deepEqual((await checkStyles(copy)).problems, []);
  });
});

test('arbitrary text sizes follow Tailwind font-size resolution without rejecting colors', async () => {
  const { scaleProblems } = await import('./style-policy.mjs');
  for (const token of [
    'text-[+14px]',
    'hover:text-[-.5rem]',
    'text-[50%]',
    'text-[xx-small]',
    'text-[x-small]',
    'text-[small]',
    'text-[medium]',
    'text-[large]',
    'text-[x-large]',
    'text-[xx-large]',
    'text-[xxx-large]',
    'text-[smaller]',
    'text-[larger]',
    'text-[calc(1rem+2px)]',
    'text-[clamp(1rem,2vw,2rem)]',
    'text-[min(1rem,2vw)]',
    'text-[max(1rem,2vw)]',
    'text-[length:var(--x)]',
    'text-[size:var(--x)]',
    'text-[percentage:var(--x)]',
    'text-[absolute-size:var(--x)]',
    'text-[relative-size:var(--x)]',
    'hover:text-(length:--x)',
  ]) {
    assert.deepEqual(scaleProblems(`const recipe = "${token}";`), [token], token);
  }
  for (const token of [
    'text-[0]',
    'text-[#fff]',
    'text-[color:var(--x)]',
    'text-[--x]',
    'text-[var(--x)]',
    'text-[rgb(10_20_30)]',
    'text-[color:calc(var(--x))]',
    'hover:text-(color:--x)',
  ]) {
    assert.deepEqual(scaleProblems(`const recipe = "${token}";`), [], token);
  }
});

test('a static template dynamic import reaches its UI module', async () => {
  const { unusedUi } = await import('./style-policy.mjs');
  await policyFixture(async (copy) => {
    await writeFile(join(copy, 'frontend/src/main.tsx'), 'void import(`@/ui/orphan`);');
    await writeFile(join(copy, 'frontend/src/ui/orphan.tsx'), 'export const Orphan = () => null;');
    assert.deepEqual(await unusedUi(copy), []);
    await writeFile(join(copy, 'frontend/src/main.tsx'), 'void import(`@/ui/${name}`);');
    assert.deepEqual(await unusedUi(copy), ['frontend/src/ui/orphan.tsx']);
  });
});

test('first-layer icon callers own their Tailwind utility sources', async () => {
  const entry = await readFile(join(root, 'frontend/src/styles/tailwind.css'), 'utf8');
  const sources = [...entry.matchAll(/^@source '([^']+)';$/gm)].map((match) => match[1]);
  const callers = [
    'drift/EntrySource',
    'project/ActivityViews',
    'project/PlanView',
    'project/ProjectsView',
    'project/ScopeNav',
    'project/parts',
    'sessions/DetailParts',
    'shell/Breadcrumb',
    'shell/UpdateNotice',
    'steering/Tripwires',
    'workstream/ChangesPanel',
  ];
  for (const caller of callers) {
    const path = `../${caller}.tsx`;
    const owned = sources.some((source) => {
      const group = source.match(/^(.*)\{([^}]+)\}(.*)$/);
      if (!group) return source === path;
      const [, prefix, alternatives, suffix] = group;
      return alternatives.split(',').some((part) => `${prefix}${part}${suffix}` === path);
    });
    assert.ok(owned, `${caller} has no Tailwind @source`);
  }
});
