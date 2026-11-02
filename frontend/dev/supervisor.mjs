import { fork, spawn, execFileSync } from 'node:child_process';
import { mkdtemp, mkdir, writeFile, rename, rm, readFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { request } from 'node:http';
import { randomBytes } from 'node:crypto';
import { join, isAbsolute } from 'node:path';
import { fileURLToPath } from 'node:url';
import { createInterface } from 'node:readline';
import { isolatedEnvironment, parseArguments } from './protocol.mjs';

const repository = fileURLToPath(new URL('../../', import.meta.url));
const workerFile = fileURLToPath(new URL('./vite-worker.mjs', import.meta.url));
const pause = (milliseconds) => new Promise((resolve) => setTimeout(resolve, milliseconds));

export function readinessRequest(origin, path, maxBytes, { deadline, signal } = {}) {
  return new Promise((resolve, reject) => {
    let settled = false,
      response,
      timer;
    const finish = (error, value) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      signal?.removeEventListener('abort', abort);
      if (error) {
        req.destroy();
        reject(error);
      } else resolve(value);
    };
    const abort = () =>
      req.destroy(
        signal.reason instanceof Error
          ? signal.reason
          : Error('Development startup was interrupted.'),
      );
    const failed = (error) => finish(error);
    const req = request(new URL(path, origin), { agent: false }, (res) => {
      response = res;
      const chunks = [];
      let size = 0;
      res.on('data', (chunk) => {
        size += chunk.length;
        if (size > maxBytes) req.destroy(Error('Readiness response exceeded its bound.'));
        else chunks.push(chunk);
      });
      res.once('end', () =>
        res.statusCode === 200
          ? finish(null, Buffer.concat(chunks).toString('utf8'))
          : finish(Error('Readiness HTTP ' + res.statusCode)),
      );
      res.once('aborted', () => finish(Error('Readiness response was aborted.')));
      // Retain an error consumer until close, including after request destroy.
      res.on('error', failed);
      res.once('close', () => {
        res.removeAllListeners('data');
        res.removeAllListeners('end');
        res.removeAllListeners('aborted');
        res.off('error', failed);
      });
    });
    req.on('error', failed);
    req.once('close', () => {
      if (!settled && !response?.complete) finish(Error('Readiness connection closed.'));
      req.off('error', failed);
    });
    timer = setTimeout(
      () => req.destroy(Error('Readiness absolute deadline exceeded.')),
      Math.max(0, (deadline ?? Date.now() + 1000) - Date.now()),
    );
    signal?.addEventListener('abort', abort, { once: true });
    if (signal?.aborted) abort();
    req.end();
  });
}

function owned(child) {
  child.stderr?.on('data', (chunk) => {
    child.diagnostic = ((child.diagnostic || '') + chunk).slice(-3000);
  });
  child.stdout?.resume(); // The real launcher can announce normally without filling its pipe.
  child.stopped = new Promise((resolve) => {
    child.once('close', (code, signal) => resolve({ code, signal }));
    child.once('error', (error) => {
      child.diagnostic = error.message;
    });
  });
  return child;
}

async function stopChild(child, worker = false) {
  if (!child || child.exitCode !== null || child.signalCode !== null) return;
  child.expectedStop = true;
  if (worker && child.connected) child.send({ type: 'stop' }, () => undefined);
  else child.kill('SIGTERM');
  let timer;
  await Promise.race([
    child.stopped,
    new Promise((resolve) => {
      timer = setTimeout(resolve, 2500);
    }),
  ]);
  clearTimeout(timer);
  if (child.exitCode === null && child.signalCode === null) {
    child.kill('SIGKILL');
    await child.stopped;
  }
}

function message(child, type, send) {
  return new Promise((resolve, reject) => {
    const finish = (error, value) => {
      clearTimeout(timer);
      child.off('message', received);
      child.off('close', ended);
      if (error) reject(error);
      else resolve(value);
    };
    const received = (value) => {
      if (value?.type === 'error') finish(Error(value.message));
      else if (value?.type === type) finish(null, value);
      else finish(Error('Unexpected Vite worker readiness message.'));
    };
    const ended = () =>
      finish(Error('Vite worker exited before readiness: ' + (child.diagnostic || '')));
    const timer = setTimeout(() => finish(Error('Vite worker readiness timeout.')), 10000);
    child.on('message', received);
    child.once('close', ended);
    child.send(send, (error) => {
      if (error) finish(error);
    });
  });
}

export async function startDevelopment(options = {}) {
  const [major, minor] = process.versions.node.split('.').map(Number);
  if (major !== 26 || minor < 10)
    throw Error('Development requires Node 26.10 or later in the Node 26 line.');
  const { port, vitePort } = parseArguments([
    '--port',
    String(options.port ?? 4581),
    '--vite-port',
    String(options.vitePort ?? 4582),
  ]);
  const root = options.root || repository;
  const pythonName =
    options.python ||
    process.env.COMPASS_TEST_PYTHON ||
    (process.platform === 'win32' ? 'python' : 'python3');
  let python;
  try {
    const result = JSON.parse(
      execFileSync(
        pythonName,
        [
          '-I',
          '-c',
          'import sys,json; print(json.dumps([sys.executable,list(sys.version_info[:2])]))',
        ],
        { encoding: 'utf8', timeout: 5000, stdio: ['ignore', 'pipe', 'pipe'] },
      ),
    );
    if (!isAbsolute(result[0]) || result[1][0] !== 3 || result[1][1] < 12)
      throw Error('Python 3.12 or later is required.');
    python = result[0];
  } catch {
    throw Error('Python 3.12 or later was not found. Use --python ABSOLUTE_PATH.');
  }
  // Refuse missing dependencies before launching either serving child.
  try {
    await readFile(join(root, 'node_modules/vite/package.json'));
  } catch {
    throw Error('Frontend dependencies are missing; run pnpm install --frozen-lockfile first.');
  }
  const scratch = await mkdtemp(join(tmpdir(), 'compass-development-'));
  await mkdir(join(scratch, 'no-executables'));
  const env = isolatedEnvironment(scratch, process.env);
  const nonce = randomBytes(32).toString('hex'),
    viteGeneration = randomBytes(16).toString('hex');
  const origin = `http://127.0.0.1:${port}`,
    viteOrigin = `http://127.0.0.1:${vitePort}`;
  let worker,
    backend,
    closing,
    interrupted = false,
    restarting = Promise.resolve(),
    failure;
  const requests = new AbortController();
  let resolveClosed;
  const closed = new Promise((resolve) => {
    resolveClosed = resolve;
  });
  const handle = {
    scratch,
    origin,
    viteOrigin,
    closed,
    ready: null,
    worker: null,
    backend: null,
    restart: () => {
      restarting = restarting.then(restart);
      return restarting;
    },
    close,
  };

  async function close() {
    if (closing) return closing;
    interrupted = true;
    requests.abort(Error('Development startup was interrupted.'));
    closing = (async () => {
      await stopChild(backend);
      await stopChild(worker, true);
      await rm(scratch, { recursive: true, force: true });
      options.signal?.removeEventListener('abort', abort);
      resolveClosed();
    })();
    return closing;
  }
  function abort() {
    void close();
  }
  const check = () => {
    if (interrupted) throw Error('Development startup was interrupted.');
  };
  options.signal?.addEventListener('abort', abort, { once: true });
  if (options.signal?.aborted) interrupted = true;

  async function restart() {
    check();
    await stopChild(backend);
    check();
    const generation = randomBytes(16).toString('hex');
    const acknowledged = await message(worker, 'generation-ready', {
      type: 'backend-generation',
      generation,
    });
    if (acknowledged.generation !== generation)
      throw Error('Vite acknowledged a foreign backend generation.');
    check();
    const manifest = {
      format: 1,
      python_origin: origin,
      vite_origin: viteOrigin,
      nonce,
      vite_generation: viteGeneration,
      backend_generation: generation,
      vite_pid: worker.pid,
    };
    const manifestPath = join(scratch, `dev-${generation}.json`);
    await writeFile(manifestPath + '.tmp', JSON.stringify(manifest), { mode: 0o600 });
    await rename(manifestPath + '.tmp', manifestPath);
    const launcher = options.backendHelper || join(root, 'compass/skills/compass/server.py');
    const args = [
      launcher,
      '--frontend-dev-manifest',
      manifestPath,
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
    ];
    backend = owned(spawn(python, args, { cwd: root, env, stdio: ['ignore', 'pipe', 'pipe'] }));
    handle.backend = backend;
    const servingChild = backend;
    servingChild.once('close', () => {
      if (!closing && !servingChild.expectedStop) {
        const error = Error(
          'Python development backend stopped unexpectedly: ' + (servingChild.diagnostic || ''),
        );
        requests.abort(error);
        if (handle.ready?.pid === servingChild.pid) {
          handle.failure = error;
          void close();
        }
      }
    });
    const deadline = Date.now() + 10000;
    while (Date.now() < deadline) {
      check();
      if (backend.exitCode !== null || backend.signalCode !== null)
        throw Error('Python development backend exited: ' + (backend.diagnostic || ''));
      try {
        const transport = {
          deadline: Math.min(deadline, Date.now() + 1000),
          signal: requests.signal,
        };
        const health = JSON.parse(await readinessRequest(origin, '/api/health', 2048, transport));
        if (health.pid !== backend.pid || health.port !== port || health.ok !== true)
          throw Error('Python readiness belongs to another process.');
        const document = await readinessRequest(origin, '/', 2_000_000, {
          deadline: Math.min(deadline, Date.now() + 1000),
          signal: requests.signal,
        });
        if (!document.includes(`<meta name="compass-dev-generation" content="${generation}">`))
          throw Error('Python development identity mismatch.');
        handle.ready = { origin, viteOrigin, pid: backend.pid, workerPid: worker.pid, generation };
        await rm(manifestPath, { force: true });
        return handle.ready;
      } catch {
        await pause(100);
      }
    }
    throw Error('Python development readiness deadline: ' + (backend.diagnostic || ''));
  }

  try {
    check();
    worker = owned(
      fork(workerFile, [], {
        cwd: root,
        env,
        execArgv: [],
        stdio: ['ignore', 'pipe', 'pipe', 'ipc'],
      }),
    );
    handle.worker = worker;
    const ready = await message(worker, 'ready', {
      type: 'start',
      root,
      scratch,
      port: vitePort,
      pythonPort: port,
      nonce,
      viteGeneration,
      backendGeneration: randomBytes(16).toString('hex'),
    });
    if (
      ready.pid !== worker.pid ||
      ready.origin !== viteOrigin ||
      ready.generation !== viteGeneration
    )
      throw Error('Vite readiness belongs to another process.');
    worker.once('close', () => {
      if (!closing) {
        handle.failure = Error('Vite development worker stopped unexpectedly.');
        void close();
      }
    });
    await restart();
    return handle;
  } catch (error) {
    // An interruption stops the children, and a child that dies under it reports its own exit;
    // that exit is the consequence of the interruption, not a second failure.
    failure = interrupted ? Error('Development startup was interrupted.') : error;
    await close();
    throw failure;
  }
}

if (process.argv[1] && fileURLToPath(import.meta.url) === process.argv[1]) {
  const controller = new AbortController();
  process.once('SIGINT', () => controller.abort());
  process.once('SIGTERM', () => controller.abort());
  let dev;
  try {
    dev = await startDevelopment({
      ...parseArguments(process.argv.slice(2)),
      signal: controller.signal,
    });
    console.log(
      `Compass development: ${dev.origin} (isolated fixtures; models, usage and native actions disabled)`,
    );
    const input = createInterface({ input: process.stdin });
    input.on('line', (line) => {
      if (line.trim() === 'r')
        dev
          .restart()
          .then(() => console.log('Python backend restarted.'))
          .catch((error) => {
            console.error(error.message);
            process.exitCode = 1;
            void dev.close();
          });
    });
    input.once('close', () => void dev.close());
    await dev.closed;
    input.close();
    if (dev.failure) throw dev.failure;
  } catch (error) {
    console.error(error.message);
    process.exitCode = 1;
    if (dev) await dev.close();
  }
}
