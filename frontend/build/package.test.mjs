import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
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

test('one variable Inter face is embedded across its three WOFF2 subsets', async () => {
  const fonts = await readFonts(root);
  assert.deepEqual(
    fonts.provenance.map(({ file }) => file),
    ['vietnamese', 'latin-ext', 'latin'].map((subset) => `fonts/inter-v20-${subset}.woff2.b64`),
  );
  assert.equal(
    fonts.css.match(/@font-face\{font-family:'Inter';font-style:normal;font-weight:100 900;/g)
      .length,
    3,
  );
  assert.equal(fonts.css.match(/data:font\/woff2;base64,/g).length, 3);
  assert.equal(fonts.css.includes('{{COMPASS_FONT_'), false);
  // Pin the bytes attached to each emitted range. Checking the assets alone misses swapped CSS slots.
  const digestByRange = new Map(
    [
      ...fonts.css.matchAll(/url\("data:font\/woff2;base64,([^"]+)"\).*?unicode-range:([^}]+)}/g),
    ].map(([, encoded, range]) => [
      range,
      createHash('sha256').update(Buffer.from(encoded, 'base64')).digest('hex'),
    ]),
  );
  for (const [subset, range, digest] of [
    [
      'Latin',
      'U+0000-00FF, U+0131, U+0152-0153, U+02BB-02BC, U+02C6, U+02DA, U+02DC, U+0304, U+0308, U+0329, U+2000-206F, U+20AC, U+2122, U+2191, U+2193, U+2212, U+2215, U+FEFF, U+FFFD',
      '3100e775e8616cd2611beecfa23a4263d7037586789b43f035236a2e6fbd4c62',
    ],
    [
      'Latin Extended',
      'U+0100-02BA, U+02BD-02C5, U+02C7-02CC, U+02CE-02D7, U+02DD-02FF, U+0304, U+0308, U+0329, U+1D00-1DBF, U+1E00-1E9F, U+1EF2-1EFF, U+2020, U+20A0-20AB, U+20AD-20C4, U+2113, U+2C60-2C7F, U+A720-A7FF',
      '34b9c504cab7a73e37b746343a449132e56cf7b5481af2cb81dc74dcff25c956',
    ],
    [
      'Vietnamese',
      'U+0102-0103, U+0110-0111, U+0128-0129, U+0168-0169, U+01A0-01A1, U+01AF-01B0, U+0300-0301, U+0303-0304, U+0308-0309, U+0323, U+0329, U+1EA0-1EF9, U+20AB',
      '5c66f9e07e90c6d4ac4922cc68d60de26c17b1858e677fb5e603fce3952b3ff2',
    ],
  ]) {
    assert.equal(digestByRange.get(range), digest, `wrong Inter subset for the ${subset} range`);
  }
  assert.equal(
    fonts.provenance.reduce((total, font) => total + font.bytes, 0),
    143576,
  );
});

test('production packaging includes full licenses and a matching document digest', async () => {
  const packed = await packageFrontend({ root, write: false });
  assert.equal(packed.metadata.format, 1);
  assert.equal(packed.metadata.frontend, 'react');
  assert.equal(packed.metadata.document.bytes, Buffer.byteLength(packed.document));
  assert.ok(packed.licenses.includes('MIT License'));
  assert.ok(packed.licenses.includes('Inter\nSource: fonts/Inter-OFL.txt\n'));
  const interLicense = await readFile(
    join(root, 'compass/skills/compass/compass_runtime/web/fonts/Inter-OFL.txt'),
  );
  assert.equal(
    createHash('sha256').update(interLicense).digest('hex'),
    '5b9321a4298cfeb6b34354164a1c3afc3db114569984c502b9b35d988fd58c57',
    'incomplete or changed Inter OFL',
  );
  assert.ok(packed.licenses.includes(interLicense.toString('utf8')));
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
  const stylesheet = new JSDOM(packed.document).window.document.querySelector('link');
  const css = Buffer.from(stylesheet.href.split(',')[1], 'base64').toString('utf8');
  // The Plan story's session-title width stays in Storybook until Plan has an app route.
  assert.equal(/max-width:28ch\b/.test(css), false, 'Plan title width leaked into app CSS');
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
    const { provenance } = await readFonts(copy);
    await writeFile(join(copy, web, provenance[0].file), 'not-a-font');
    await assert.rejects(readFonts(copy), /invalid base64/);
  });
});

test('a WOFF2 whose recorded size or digest changes is rejected', async () => {
  await copiedSource('s1-02-compass-font-provenance-', async (copy, web) => {
    const file = join(copy, web, 'fonts/SOURCES.txt');
    const original = await readFile(file, 'utf8');
    for (const [field, replacement] of [
      [/Decoded bytes: \d+/, 'Decoded bytes: 1'],
      [/SHA-256: [a-f0-9]{64}/, `SHA-256: ${'0'.repeat(64)}`],
    ]) {
      await writeFile(file, original.replace(field, replacement));
      await assert.rejects(readFonts(copy), /font differs from SOURCES\.txt/);
    }
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
