import assert from 'node:assert/strict';
import { test } from 'node:test';
import { JSDOM } from 'jsdom';
import { createDocument, readFonts, packageFrontend } from './package.mjs';
import { fileURLToPath } from 'node:url';
import { cp, mkdir, mkdtemp, rm, symlink, readFile, writeFile, stat } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { execFileSync } from 'node:child_process';

const root = fileURLToPath(new URL('../../', import.meta.url));

test('hostile JavaScript and CSS values remain exact embedded bytes', () => {
  const javascript =
    'const values=["</script>","<!--","<script","</head>",String.raw`</ScRiPt>`]; window.answer=values;';
  const css = ':root{--example:"</style>"}';
  const document = new JSDOM(createDocument(javascript, css)).window.document;
  const scripts = [...document.querySelectorAll('script')];
  assert.equal(scripts.length, 1);
  assert.equal(scripts[0].type, 'module');
  const embedded = Buffer.from(scripts[0].src.split(',')[1], 'base64').toString();
  assert.equal(embedded.slice(0, javascript.length), javascript);
  assert.match(embedded.slice(javascript.length), /^\n\/\/# sourceURL=[^\r\n]+\n$/);
  assert.equal(
    Buffer.from(document.querySelector('link').href.split(',')[1], 'base64').toString(),
    css,
  );
  assert.equal(document.querySelectorAll('#root').length, 1);
  assert.equal(document.querySelectorAll('meta[name="compass-focus"]').length, 0);
});

test('canonical font descriptors and all fifteen WOFF2 subsets are embedded', async () => {
  const fonts = await readFonts(root);
  assert.equal(fonts.provenance.length, 15);
  assert.equal(fonts.css.match(/@font-face/g).length, 15);
  assert.equal(fonts.css.match(/data:font\/woff2;base64,/g).length, 15);
  assert.equal(fonts.css.includes('{{COMPASS_FONT_'), false);
  assert.equal(
    fonts.provenance.reduce((total, font) => total + font.bytes, 0),
    142840,
  );
});

test('production packaging includes full licenses and a matching document digest', async () => {
  const packed = await packageFrontend({ root, write: false });
  assert.equal(packed.metadata.format, 1);
  assert.equal(packed.metadata.frontend, 'react');
  assert.equal(packed.metadata.document.bytes, Buffer.byteLength(packed.document));
  assert.ok(packed.licenses.includes('MIT License'));
  assert.ok(packed.licenses.includes('SIL OPEN FONT LICENSE'));
  assert.ok(packed.metadata.provenance.packages.some((pkg) => pkg.name === 'react'));
  assert.ok(packed.metadata.provenance.packages.some((pkg) => pkg.name === 'react-dom'));
  assert.ok(packed.metadata.provenance.packages.some((pkg) => pkg.name === 'scheduler'));
  assert.ok(packed.licenses.includes('Copyright (c) 2023 shadcn'));
  assert.ok(packed.metadata.provenance.sources.some((source) => source.file === 'components.json'));
  assert.ok(
    packed.metadata.provenance.sources.some(
      (source) => source.file === 'frontend/src/styles/tailwind.css',
    ),
  );
  assert.equal(packed.document.includes('sourceMappingURL'), false);
  assert.equal(packed.document.includes('compass-focus'), false);
});

async function copiedSource(prefix, use) {
  const copy = await mkdtemp(join(tmpdir(), prefix));
  try {
    for (const file of [
      'package.json',
      'pnpm-lock.yaml',
      '.node-version',
      '.gitattributes',
      'components.json',
    ])
      await cp(join(root, file), join(copy, file));
    await cp(join(root, 'frontend'), join(copy, 'frontend'), { recursive: true });
    const web = 'compass/skills/compass/compass_runtime/web';
    await mkdir(join(copy, web), { recursive: true });
    await cp(join(root, web), join(copy, web), { recursive: true });
    await symlink(
      join(root, 'node_modules'),
      join(copy, 'node_modules'),
      process.platform === 'win32' ? 'junction' : 'dir',
    );
    await use(copy, web);
  } finally {
    await rm(copy, { recursive: true, force: true });
  }
}

test('two clean builds in distinct paths and a plugin-version-only bump match', async () => {
  let first;
  await copiedSource('compass-package-a-', async (copy) => {
    first = await packageFrontend({ root: copy, write: false });
  });
  await copiedSource('compass-package-b-', async (copy) => {
    await mkdir(join(copy, 'compass/.claude-plugin'), { recursive: true });
    await writeFile(join(copy, 'compass/.claude-plugin/plugin.json'), '{"version":"99.99.99"}\n');
    const second = await packageFrontend({ root: copy, write: false });
    assert.deepEqual(second, first);
  });
});

/* One copied tree for every check-mode case: each one damages a single output, asserts, and puts the bytes back.
   A copy and a fresh build per case made this file the slowest in `pnpm test` (measured 2026-10-28). */
test('check mode leaves outputs untouched and rejects each stale one without rewriting it', async (t) => {
  await copiedSource('compass-package-check-', async (copy, web) => {
    await packageFrontend({ root: copy });
    const damage = async (name, bytes, verify) => {
      const file = join(copy, web, name);
      const original = await readFile(file);
      await writeFile(file, bytes(original));
      try {
        await verify(file);
      } finally {
        await writeFile(file, original);
      }
    };
    await t.test('a current tree passes and is left untouched', async () => {
      const file = join(copy, web, 'react.html');
      const before = await stat(file);
      await packageFrontend({ root: copy, check: true });
      assert.equal((await stat(file)).mtimeMs, before.mtimeMs);
    });
    await t.test('a stale react.html is rejected and kept', () =>
      damage(
        'react.html',
        () => Buffer.from('corrupt artifact\n'),
        async (file) => {
          await assert.rejects(
            packageFrontend({ root: copy, check: true }),
            /stale tracked react.html/,
          );
          assert.equal(await readFile(file, 'utf8'), 'corrupt artifact\n');
        },
      ),
    );
    for (const name of ['react.html', 'react.integrity.json', 'react-licenses.txt'])
      await t.test(`a BOM in ${name} is rejected without rewriting bytes`, () =>
        damage(
          name,
          (original) => Buffer.concat([Buffer.from([0xef, 0xbb, 0xbf]), original]),
          async (file) => {
            const changed = await readFile(file);
            const before = await stat(file);
            await assert.rejects(
              packageFrontend({ root: copy, check: true }),
              new RegExp('stale tracked ' + name.replaceAll('.', '\\.')),
            );
            assert.deepEqual(await readFile(file), changed);
            assert.equal((await stat(file)).mtimeMs, before.mtimeMs);
          },
        ),
      );
  });
});

test('a corrupt canonical font fails instead of silently falling back', async () => {
  await copiedSource('compass-package-font-', async (copy, web) => {
    await writeFile(join(copy, web, 'fonts/space-grotesk-v22-latin.woff2.b64'), 'not-a-font');
    await assert.rejects(readFonts(copy), /invalid base64/);
  });
});

test('an actual autocrlf checkout preserves the served page and every candidate artifact', async () => {
  const temporary = await mkdtemp(join(tmpdir(), 'compass-line-endings-'));
  try {
    const source = join(temporary, 'source'),
      checkout = join(temporary, 'checkout');
    await mkdir(source);
    await writeFile(
      join(source, '.gitattributes'),
      (await readFile(join(root, '.gitattributes'), 'utf8')) +
        '\n.autocrlf-control.txt text !eol\n',
    );
    await writeFile(join(source, '.autocrlf-control.txt'), 'control\n');
    const binaryControl = Buffer.from([0, 255, 13, 10, 0, 65, 10]);
    await writeFile(join(source, '.autocrlf-binary.bin'), binaryControl);
    await cp(join(root, 'compass'), join(source, 'compass'), {
      recursive: true,
      filter: (path) => !path.split(/[\\/]/).includes('__pycache__'),
    });
    const git = (...args) =>
      execFileSync(
        'git',
        [
          '-c',
          'core.hooksPath=' + join(temporary, 'empty-hooks'),
          '-c',
          'commit.gpgsign=false',
          ...args,
        ],
        { cwd: source, encoding: 'utf8', timeout: 10000, stdio: ['ignore', 'pipe', 'pipe'] },
      );
    await mkdir(join(temporary, 'empty-hooks'));
    git('init');
    git('add', '--', '.gitattributes', '.autocrlf-control.txt', '.autocrlf-binary.bin', 'compass');
    git(
      '-c',
      'user.name=Frontend test',
      '-c',
      'user.email=frontend-test@example.invalid',
      'commit',
      '-m',
      'fixture',
    );
    git('-c', 'core.autocrlf=true', 'clone', '--no-local', source, checkout);
    assert.equal(await readFile(join(checkout, '.autocrlf-control.txt'), 'utf8'), 'control\r\n');
    assert.deepEqual(await readFile(join(checkout, '.autocrlf-binary.bin')), binaryControl);
    const python =
      process.env.COMPASS_TEST_PYTHON || (process.platform === 'win32' ? 'python' : 'python3');
    const digest = (directory) =>
      execFileSync(
        python,
        [
          '-c',
          'import sys,hashlib;sys.path.insert(0,sys.argv[1]);from compass_runtime.web.page import load_frontend_page;print(hashlib.sha256(load_frontend_page()).hexdigest())',
          join(directory, 'compass/skills/compass'),
        ],
        { encoding: 'utf8', timeout: 10000 },
      ).trim();
    assert.equal(digest(source), digest(checkout));
    const web = 'compass/skills/compass/compass_runtime/web';
    for (const name of ['react.html', 'react.integrity.json', 'react-licenses.txt']) {
      assert.deepEqual(
        await readFile(join(checkout, web, name)),
        await readFile(join(source, web, name)),
      );
    }
  } finally {
    await rm(temporary, { recursive: true, force: true });
  }
});
