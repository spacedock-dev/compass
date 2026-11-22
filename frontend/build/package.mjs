import { createHash } from 'node:crypto';
import { readFile, writeFile, readdir, realpath } from 'node:fs/promises';
import { dirname, resolve, relative, isAbsolute, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { build } from 'vite';
import { JSDOM } from 'jsdom';

export const ROOT = fileURLToPath(new URL('../../', import.meta.url));
const WEB = 'compass/skills/compass/compass_runtime/web';
const OUTPUTS = ['react.html', 'react.integrity.json', 'react-licenses.txt'];
const sha256 = (value) => createHash('sha256').update(value).digest('hex');
const ordered = (a, b) => (a < b ? -1 : a > b ? 1 : 0);
const utf8 = (value) =>
  typeof value === 'string' ? value : new TextDecoder('utf-8', { fatal: true }).decode(value);
const lf = (value) => utf8(value).replace(/\r\n/g, '\n');
function fail(message) {
  throw new Error(`Frontend packaging: ${message}`);
}

export function stableJson(value) {
  const sort = (value) =>
    Array.isArray(value)
      ? value.map(sort)
      : value && typeof value === 'object'
        ? Object.fromEntries(
            Object.keys(value)
              .sort(ordered)
              .map((key) => [key, sort(value[key])]),
          )
        : value;
  return JSON.stringify(sort(value), null, 2) + '\n';
}

export function createDocument(
  javascript,
  css,
  template = '<!doctype html><html lang="en"><head><meta charset="UTF-8"><title>Compass</title></head><body><div id="root"></div><script type="module" src="entry.js"></script></body></html>',
) {
  const dom = new JSDOM(template);
  try {
    const document = dom.window.document;
    const scripts = [...document.querySelectorAll('script')];
    if (scripts.length !== 1 || scripts[0].type !== 'module' || !scripts[0].hasAttribute('src'))
      fail('expected one external Vite module entry');
    if (
      document.querySelectorAll('#root').length !== 1 ||
      document.querySelector('[name="compass-focus"]')
    )
      fail('invalid root/focus template');
    if (document.querySelector('style,iframe,object,embed,img,video,audio'))
      fail('unexpected document asset surface');
    for (const element of document.querySelectorAll('*')) {
      if ([...element.attributes].some((attribute) => /^on/i.test(attribute.name)))
        fail('event attributes are not permitted');
    }
    for (const link of document.querySelectorAll('link')) {
      if (link.rel !== 'stylesheet') fail('unexpected document link asset');
      link.remove();
    }
    const stylesheet = document.createElement('link');
    stylesheet.rel = 'stylesheet';
    stylesheet.href = 'data:text/css;base64,' + Buffer.from(css).toString('base64');
    document.head.append(stylesheet);
    const script = scripts[0];
    for (const attribute of [...script.attributes]) script.removeAttribute(attribute.name);
    script.type = 'module';
    // Chromium copied the full data URL into callback source locations; repeated
    // production drift loads reached 8 GiB RSS. A short name bounds those copies.
    script.src =
      'data:text/javascript;base64,' +
      Buffer.from(javascript + '\n//# sourceURL=compass-bundle.js\n').toString('base64');
    script.textContent = '';
    const result = dom.serialize() + '\n';
    if ((result.match(/<\/head>/g) || []).length !== 1) fail('head injection point must be unique');
    return result;
  } finally {
    dom.window.close();
  }
}

export async function readFonts(root) {
  const page = lf(await readFile(join(root, WEB, 'page.py')));
  const pairs = [
    ...page.matchAll(
      /\(\s*"(fonts\/[a-z0-9.-]+\.woff2\.b64)",\s*"(\{\{COMPASS_FONT_[A-Z0-9_]+\}\})",?\s*\)/g,
    ),
  ];
  const styles = lf(await readFile(join(root, WEB, 'styles.css')));
  const faces = styles.match(/^@font-face\{.*\}$/gm) || [];
  const sources = lf(await readFile(join(root, WEB, 'fonts/SOURCES.txt')));
  const sourceRows = [
    ...sources.matchAll(
      /^([a-z0-9.-]+\.woff2\.b64)\n {2}Source: https:\/\/\S+\n {2}Decoded bytes: (\d+)\n {2}SHA-256: ([a-f0-9]{64})$/gm,
    ),
  ];
  const sourcePins = new Map(
    sourceRows.map(([, file, bytes, digest]) => [
      `fonts/${file}`,
      { bytes: Number(bytes), digest },
    ]),
  );
  const subsetCount = 3;
  if (
    pairs.length !== subsetCount ||
    faces.length !== subsetCount ||
    new Set(pairs.map((pair) => pair[1])).size !== subsetCount ||
    sourceRows.length !== subsetCount ||
    sourcePins.size !== subsetCount
  )
    fail('canonical three-subset font shape changed');
  const provenance = [],
    output = [];
  for (const [, file, slot] of pairs) {
    const matching = faces.filter((face) => face.includes(slot));
    if (matching.length !== 1 || matching[0].split(slot).length !== 2)
      fail(`ambiguous font descriptor ${file}`);
    const encoded = utf8(await readFile(join(root, WEB, file))).replace(/\s/g, '');
    if (!/^(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?$/.test(encoded))
      fail(`invalid base64 ${file}`);
    const payload = Buffer.from(encoded, 'base64');
    if (payload.subarray(0, 4).toString() !== 'wOF2' || payload.toString('base64') !== encoded)
      fail(`invalid WOFF2 ${file}`);
    const digest = sha256(payload);
    const pin = sourcePins.get(file);
    if (pin?.bytes !== payload.length || pin.digest !== digest)
      fail(`font differs from SOURCES.txt: ${file}`);
    provenance.push({ file, bytes: payload.length, sha256: digest, face: matching[0] });
    output.push(matching[0].replace(slot, 'data:font/woff2;base64,' + encoded));
  }
  return { css: output.join('\n') + '\n', provenance };
}

async function packageOwner(moduleId, modulesRoot) {
  if (moduleId.startsWith('\0')) {
    if (moduleId === '\0rolldown/runtime.js') return null;
    fail(`unknown generated module ${moduleId}`);
  }
  if (!moduleId.includes('node_modules')) return null;
  let directory = dirname(moduleId);
  const physicalModules = await realpath(modulesRoot);
  const physicalModule = await realpath(moduleId);
  const dependencyPath = relative(physicalModules, physicalModule);
  if (dependencyPath.startsWith('..') || isAbsolute(dependencyPath))
    fail('dependency module leaves the resolved dependency root');
  while (directory.length > 1) {
    try {
      const manifest = JSON.parse(await readFile(join(directory, 'package.json'), 'utf8'));
      if (typeof manifest.name === 'string' && typeof manifest.version === 'string')
        return { name: manifest.name, version: manifest.version };
    } catch (error) {
      if (error.code !== 'ENOENT') throw error;
    }
    const parent = dirname(directory);
    if (parent === directory) break;
    directory = parent;
  }
  fail('dependency module has no package owner');
}

async function authoredSources(root) {
  const files = [
    '.gitattributes',
    '.node-version',
    'package.json',
    'components.json',
    'pnpm-lock.yaml',
    'frontend/index.html',
    'frontend/vite.config.mts',
    'frontend/build/package.mjs',
    'frontend/build/xterm-integrity.mjs',
    'frontend/build/shadcn-LICENSE.txt',
    `${WEB}/styles.css`,
    `${WEB}/page.py`,
    `${WEB}/fonts/SOURCES.txt`,
    `${WEB}/fonts/Inter-OFL.txt`,
    `${WEB}/vendor/SOURCES.txt`,
    `${WEB}/vendor/xterm-LICENSE.txt`,
  ];
  async function walk(directory) {
    for (const entry of await readdir(join(root, directory), { withFileTypes: true })) {
      const name = directory + '/' + entry.name;
      if (entry.isDirectory()) await walk(name);
      else if (entry.isFile() && !/\.test\./.test(name)) files.push(name);
      else if (!entry.isFile()) fail(`unsupported source filesystem entry ${name}`);
    }
  }
  await walk('frontend/src');
  return Promise.all(
    [...new Set(files)]
      .sort(ordered)
      .map(async (file) => ({ file, sha256: sha256(lf(await readFile(join(root, file)))) })),
  );
}

export async function packageFrontend({ root = ROOT, write = true, check = false } = {}) {
  root = await realpath(resolve(root));
  const output = await build({
    configFile: join(root, 'frontend/vite.config.mts'),
    configLoader: 'native',
    logLevel: 'error',
    build: {
      write: false,
      sourcemap: false,
      modulePreload: false,
      cssCodeSplit: false,
      assetsInlineLimit: Infinity,
      license: { fileName: 'licenses.json' },
      rolldownOptions: { output: { codeSplitting: false } },
    },
  });
  if (Array.isArray(output)) fail('multiple build outputs are unsupported');
  const chunks = output.output.filter((item) => item.type === 'chunk');
  const cssAssets = output.output.filter(
    (item) => item.type === 'asset' && item.fileName.endsWith('.css'),
  );
  const htmlAsset = output.output.find(
    (item) => item.type === 'asset' && item.fileName === 'index.html',
  );
  const licenseAsset = output.output.find(
    (item) => item.type === 'asset' && item.fileName === 'licenses.json',
  );
  if (
    chunks.length !== 1 ||
    !chunks[0].isEntry ||
    chunks[0].imports.length ||
    chunks[0].dynamicImports.length ||
    cssAssets.length > 1 ||
    !htmlAsset ||
    !licenseAsset
  )
    fail('build must contain one fully bundled entry');
  const allowed = new Set([
    chunks[0].fileName,
    ...cssAssets.map((item) => item.fileName),
    'index.html',
    'licenses.json',
  ]);
  if (output.output.some((item) => !allowed.has(item.fileName))) fail('unexpected emitted asset');
  if (/sourceMappingURL|import\.meta|\bimport\s*\(/.test(chunks[0].code))
    fail('unsupported source map or chunk-relative runtime import');
  const fontData = await readFonts(root);
  const css = fontData.css + (cssAssets[0] ? utf8(cssAssets[0].source) : '');
  if (/@import\b/i.test(css)) fail('CSS imports are not self-contained');
  for (const match of css.matchAll(/url\s*\(\s*([^)]*)\)/gi)) {
    if (!/^['"]?data:/i.test(match[1])) fail('CSS contains a non-embedded URL');
  }
  const document = createDocument(chunks[0].code, css, utf8(htmlAsset.source));
  const rawLicenses = JSON.parse(utf8(licenseAsset.source));
  if (!Array.isArray(rawLicenses)) fail('license inventory is not an array');
  const packages = [];
  const owned = new Set();
  for (const moduleId of chunks[0].moduleIds) {
    const owner = await packageOwner(moduleId, join(root, 'node_modules'));
    if (owner) owned.add(`${owner.name}@${owner.version}`);
    else if (!moduleId.startsWith('\0') && !isAbsolute(moduleId)) fail('unknown module id');
    else if (!moduleId.startsWith('\0') && !moduleId.includes('node_modules')) {
      const source = relative(root, moduleId);
      if (source.startsWith('..') || isAbsolute(source)) fail('authored module leaves source root');
    }
  }
  const sections = [
    'Third-party notices for the bundled React core.\nOptional xterm assets are local installed resources, not part of this core bundle.',
  ];
  for (const item of rawLicenses.sort((a, b) => ordered(a.name, b.name))) {
    if (
      !item.name ||
      !item.version ||
      !item.identifier ||
      typeof item.text !== 'string' ||
      !item.text.trim()
    )
      fail('missing bundled package license');
    if (!owned.has(`${item.name}@${item.version}`)) fail('license has no bundled module owner');
    owned.delete(`${item.name}@${item.version}`);
    const text = lf(item.text).trimEnd() + '\n';
    packages.push({
      name: item.name,
      version: item.version,
      license: item.identifier,
      licenseFile: 'LICENSE',
      sha256: sha256(text),
    });
    sections.push(`${item.name}@${item.version} (${item.identifier})\n\n${text}`);
  }
  if (owned.size) fail('bundled dependency has no full license notice');
  const copiedLicense = lf(await readFile(join(root, 'frontend/build/shadcn-LICENSE.txt')));
  if (!copiedLicense.trim()) fail('missing shadcn copied-source notice');
  sections.push(
    `shadcn/ui copied source (MIT)\nSource: https://github.com/shadcn-ui/ui/blob/main/LICENSE.md\n\n${copiedLicense.trimEnd()}\n`,
  );
  for (const [title, file] of [
    ['Inter', 'fonts/Inter-OFL.txt'],
    ['Optional xterm.js@6.0.0', 'vendor/xterm-LICENSE.txt'],
  ]) {
    const text = lf(await readFile(join(root, WEB, file)));
    if (!text.trim()) fail(`missing ${title} notice`);
    sections.push(`${title}\nSource: ${file}\n\n${text.trimEnd()}\n`);
  }
  const licenses = sections.join('\n\n' + '='.repeat(72) + '\n\n') + '\n';
  const terminal = async (file) => {
    const bytes = await readFile(join(root, WEB, file));
    return { file, bytes: bytes.length, sha256: sha256(bytes) };
  };
  const metadata = {
    format: 1,
    frontend: 'react',
    document: { file: OUTPUTS[0], bytes: Buffer.byteLength(document), sha256: sha256(document) },
    licenses: { file: OUTPUTS[2], bytes: Buffer.byteLength(licenses), sha256: sha256(licenses) },
    provenance: { sources: await authoredSources(root), fonts: fontData.provenance, packages },
    optionalTerminal: {
      javascript: await terminal('vendor/xterm.js'),
      stylesheet: await terminal('vendor/xterm.css'),
    },
  };
  const contents = [document, stableJson(metadata), licenses];
  if (check) {
    for (let i = 0; i < OUTPUTS.length; i++) {
      if (!(await readFile(join(root, WEB, OUTPUTS[i]))).equals(Buffer.from(contents[i], 'utf8')))
        fail(`stale tracked ${OUTPUTS[i]}; run pnpm build`);
    }
  } else if (write) {
    // Produce all content before updating any artifact; interrupted writes fail
    // runtime integrity validation rather than silently serving another renderer.
    for (let i = 0; i < OUTPUTS.length; i++)
      await writeFile(join(root, WEB, OUTPUTS[i]), contents[i]);
  }
  return { document, metadata, licenses };
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const args = process.argv.slice(2);
  if (args.some((argument) => argument !== '--check'))
    fail('usage: node frontend/build/package.mjs [--check]');
  try {
    const result = await packageFrontend({ check: args.includes('--check') });
    console.log(
      `React core ${result.metadata.document.bytes} bytes; ${result.metadata.provenance.fonts.length} fonts; ${result.metadata.provenance.packages.length} bundled licenses.`,
    );
  } catch (error) {
    console.error(String(error.message || error));
    process.exitCode = 1;
  }
}
