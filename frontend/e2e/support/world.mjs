/*
 * The one place that decides how the React side of a browser proof is served.
 *
 * Default (development): `startDevelopment`, the supervisor the contributor runs. Vite serves modules over
 * HMR and Python serves the document and every /api route. That is what every proof has always exercised,
 * and it stays the default.
 *
 * `COMPASS_E2E_BUNDLE=production`: the Python backend serves a PRODUCTION-built document, as `server.py`
 * serves it to a reader. No Vite child, no HMR, no `--frontend-dev-manifest`, the minified
 * single-file page, and the lazy local xterm assets from the vendored files. Dev mode catches what a
 * development server shows; this mode catches what only the shipped bytes show: minification, dead-code
 * elimination, CSS order, StrictMode being a development-only double effect, source maps being absent.
 *
 * Two kinds of root reach here. The repository itself: its tracked `react.html` is what is served, byte for
 * byte, so the proof is about the artifact `pnpm build:check` pins. A scratch copy (a proof that swaps the
 * entry for a harness, or applies a deliberate mutation): the copy is packaged first with the same
 * `packageFrontend` the tracked artifact is produced by, into the copy's own web directory, so the served
 * page is that copy's production build and the tracked tree is never written.
 *
 * `startReactWorld` returns the handle `startDevelopment` returns, so a caller changes its import and nothing
 * else. `viteOrigin` equals `origin` in production mode: a page may be allowed to talk to it and no request
 * ever goes elsewhere.
 */
import { execFileSync, spawn } from 'node:child_process';
import { copyFile, mkdir, mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { packageFrontend } from '../../build/package.mjs';
import { isolatedEnvironment } from '../../dev/protocol.mjs';
import { startDevelopment } from '../../dev/supervisor.mjs';

const REPOSITORY = fileURLToPath(new URL('../../../', import.meta.url));

export const PRODUCTION = process.env.COMPASS_E2E_BUNDLE === 'production';

if (
  process.env.COMPASS_E2E_BUNDLE &&
  !PRODUCTION &&
  process.env.COMPASS_E2E_BUNDLE !== 'development'
)
  throw new Error('COMPASS_E2E_BUNDLE must be "production" or "development" when it is set.');

/* The files `packageFrontend` reads from the root besides `frontend/` and `compass/`, which a scratch copy
   already carries. */
const ROOT_FILES = [
  '.gitattributes',
  '.node-version',
  'package.json',
  'pnpm-lock.yaml',
  'components.json',
];

function resolvePython(name) {
  const python =
    name ||
    process.env.COMPASS_TEST_PYTHON ||
    (process.platform === 'win32' ? 'python' : 'python3');
  return execFileSync(python, ['-I', '-c', 'import sys; print(sys.executable)'], {
    encoding: 'utf8',
    timeout: 5000,
  }).trim();
}

/* Package a scratch copy once per process and root, so a proof that starts several worlds over one copy
   builds it once. */
const packaged = new Map();
async function packageCopy(root) {
  const key = resolve(root);
  if (!packaged.has(key)) {
    packaged.set(
      key,
      (async () => {
        for (const file of ROOT_FILES)
          await copyFile(join(REPOSITORY, file), join(key, file)).catch(() => undefined);
        await packageFrontend({ root: key });
      })(),
    );
  }
  return packaged.get(key);
}

function stopped(child) {
  return child.exitCode !== null || child.signalCode !== null;
}

async function stop(child) {
  if (!child || stopped(child)) return;
  child.kill('SIGTERM');
  await new Promise((done) => {
    const timer = setTimeout(() => {
      child.kill('SIGKILL');
      done();
    }, 3000);
    child.once('close', () => {
      clearTimeout(timer);
      done();
    });
  });
}

async function startProduction(options) {
  const root = options.root || REPOSITORY;
  if (resolve(root) !== resolve(REPOSITORY)) await packageCopy(root);
  const port = options.port;
  const python = resolvePython(options.python);
  const scratch = await mkdtemp(join(tmpdir(), 'compass-production-'));
  await mkdir(join(scratch, 'no-executables'));
  const origin = `http://127.0.0.1:${port}`;
  const launcher = options.backendHelper || join(root, 'compass/skills/compass/server.py');
  // The development manifest forces every opt-out; there is none here, so the same flags are passed by hand
  // and a fixture that lifts some of them still sees the same starting point.
  const args = [
    launcher,
    '--host',
    '127.0.0.1',
    '--port',
    String(port),
    '--no-observer-model',
    '--no-usage',
    '--no-git',
    '--no-focus',
    '--no-events',
    '--no-spacedock',
    '--no-tripwires',
    '--no-reach',
    '--no-ask',
    '--no-history',
    '--no-update-check',
  ];
  const env = { ...isolatedEnvironment(scratch, process.env), COMPASS_E2E_BUNDLE: 'production' };
  let backend;
  let closing = null;
  const handle = {
    scratch,
    origin,
    viteOrigin: origin,
    production: true,
    worker: null,
    backend: null,
    ready: null,
    failure: null,
    closed: null,
    restart: async () => {
      await stop(backend);
      await launch();
    },
    close: () => {
      closing ??= (async () => {
        await stop(backend);
        await rm(scratch, { recursive: true, force: true });
        resolveClosed();
      })();
      return closing;
    },
  };
  let resolveClosed;
  handle.closed = new Promise((done) => {
    resolveClosed = done;
  });

  async function launch() {
    backend = spawn(python, args, { cwd: root, env, stdio: ['ignore', 'pipe', 'pipe'] });
    handle.backend = backend;
    backend.stderr.on('data', (chunk) => {
      backend.diagnostic = ((backend.diagnostic || '') + chunk).slice(-3000);
    });
    backend.stdout.resume();
    const deadline = Date.now() + 15000;
    for (;;) {
      if (stopped(backend))
        throw new Error('Python production backend exited: ' + (backend.diagnostic || ''));
      try {
        const health = await (
          await fetch(origin + '/api/health', { signal: AbortSignal.timeout(1000) })
        ).json();
        if (health.ok !== true || health.pid !== backend.pid || health.port !== port)
          throw new Error('Python readiness belongs to another process.');
        const page = await (
          await fetch(origin + '/', { signal: AbortSignal.timeout(2000) })
        ).text();
        if (/compass-dev-generation/.test(page))
          throw new Error('The production page carries a development generation.');
        handle.ready = { origin, viteOrigin: origin, pid: backend.pid, workerPid: null };
        return;
      } catch (error) {
        if (/belongs to another|development generation/.test(error.message)) throw error;
        if (Date.now() > deadline)
          throw new Error(
            'Python production readiness deadline: ' + (backend.diagnostic || error.message),
            { cause: error },
          );
        await new Promise((done) => setTimeout(done, 100));
      }
    }
  }

  try {
    await launch();
    return handle;
  } catch (error) {
    await handle.close();
    throw error;
  }
}

/** `startDevelopment`'s contract, honouring `COMPASS_E2E_BUNDLE`. `vitePort` is ignored in production. */
export function startReactWorld(options = {}) {
  return PRODUCTION ? startProduction(options) : startDevelopment(options);
}
