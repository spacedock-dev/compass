'use strict';
// The owned-process observer's preload for Node and Bun children. Not shipped.
//
// `scripts/owned_observer.py` puts this file on NODE_OPTIONS (`--require`) and BUN_OPTIONS
// (`--preload`) of a Compass server it starts, so every Node or Bun program in that server's
// process tree loads it before its own code, and passes it on through the environment it
// inherits. It does nothing unless COMPASS_OBSERVE_LOG names a file, and it never throws into
// the program it watches: every hook calls the original whatever the logging did.
//
// What it records and why is owned by docs/design-owned-process-observer.md. Arguments longer
// than 64 characters or holding a newline are recorded as their length only, because a model
// call's system prompt is an argument and its words do not belong in a trace.
(() => {
  const LOG = process.env.COMPASS_OBSERVE_LOG;
  if (!LOG || globalThis.__compassOwnedObserver) {
    return;
  }
  globalThis.__compassOwnedObserver = true;

  const fs = require('node:fs');
  const path = require('node:path');
  let fd;
  try {
    fd = fs.openSync(LOG, 'a');
  } catch {
    return;
  }
  const runtime = process.versions.bun ? 'bun' : 'node';
  const MAX_ARG = 64;

  function emit(kind, op, fields) {
    try {
      const record = {
        t: Date.now() / 1000,
        src: runtime,
        pid: process.pid,
        ppid: process.ppid,
        kind,
        op,
        ...fields,
      };
      fs.writeSync(fd, `${JSON.stringify(record)}\n`);
    } catch {
      // The trace is never allowed to change what the watched program does.
    }
  }

  function redact(value) {
    const text = String(value);
    return text.length > MAX_ARG || text.includes('\n') ? `<${text.length} chars>` : text;
  }

  function program(file) {
    return file === undefined || file === null ? '' : path.basename(String(file));
  }

  // Wrap `owner[name]` so `record(args)` runs first. `depth` is shared by one family of
  // wrappers, so a wrapped call that reaches another wrapper of the same family synchronously
  // (`exec` calls the exported `execFile`; Bun's `spawn` calls `Bun.spawn`) is recorded once.
  function wrap(owner, name, family, record) {
    const original = owner?.[name];
    if (typeof original !== 'function') {
      return;
    }
    const wrapped = function (...args) {
      if (family.depth === 0) {
        try {
          record(args, this);
        } catch {
          // Recording failed; the call still runs.
        }
      }
      family.depth += 1;
      try {
        return new.target ? Reflect.construct(original, args, new.target) : original.apply(this, args);
      } finally {
        family.depth -= 1;
      }
    };
    try {
      Object.defineProperty(wrapped, 'name', { value: original.name });
      Object.setPrototypeOf(wrapped, original);
      if (original.prototype) {
        wrapped.prototype = original.prototype;
      }
      owner[name] = wrapped;
    } catch {
      // A read-only property stays unwatched; the design record lists which.
    }
  }

  emit('start', 'process', { program: program(process.execPath) });
  process.on('exit', (code) => emit('exit', 'process', { code }));

  // Program launches.
  const launches = { depth: 0 };
  const childProcess = require('node:child_process');
  for (const name of ['spawn', 'spawnSync', 'execFile', 'execFileSync', 'fork']) {
    wrap(childProcess, name, launches, (args) => {
      const argv = Array.isArray(args[1]) ? args[1] : [];
      emit('launch', `child_process.${name}`, {
        program: name === 'fork' ? program(process.execPath) : program(args[0]),
        argv: [name === 'fork' ? redact(args[0]) : redact(args[0]), ...argv.map(redact)],
      });
    });
  }
  for (const name of ['exec', 'execSync']) {
    wrap(childProcess, name, launches, (args) => {
      emit('launch', `child_process.${name}`, { program: 'sh', argv: ['sh', '-c', redact(args[0])] });
    });
  }
  if (typeof Bun !== 'undefined') {
    for (const name of ['spawn', 'spawnSync']) {
      wrap(Bun, name, launches, (args) => {
        const first = args[0];
        const argv = Array.isArray(first) ? first : first?.cmd || [];
        emit('launch', `Bun.${name}`, { program: program(argv[0]), argv: argv.map(redact) });
      });
    }
  }

  // Connections. Every Node TCP or TLS client socket connects through
  // `net.Socket.prototype.connect`, `http`, `https`, `tls` and `fetch` included; Bun's `fetch`
  // and `http` do not, so they are wrapped by name as well, and the report counts a Bun
  // request as its own connection.
  const sockets = { depth: 0 };
  const net = require('node:net');
  wrap(net.Socket.prototype, 'connect', sockets, (args, socket) => {
    let options = args[0];
    if (Array.isArray(options)) {
      options = options[0];
    }
    if (options === null || typeof options !== 'object') {
      options =
        typeof options === 'string' && Number.isNaN(Number(options))
          ? { path: options }
          : { port: options, host: typeof args[1] === 'string' ? args[1] : undefined };
    }
    const tls = socket?.constructor?.name === 'TLSSocket';
    // Node takes a truthy `path` as a pipe; http's agent hands every socket `path: null`.
    if (options.path) {
      emit('connect', 'socket.connect', { family: 'unix', path: redact(options.path) });
    } else {
      emit('connect', 'socket.connect', {
        family: 'inet',
        host: options.host === undefined ? 'localhost' : String(options.host),
        port: Number(options.port),
        tls,
      });
    }
  });

  const requests = { depth: 0 };
  function endpoint(target, fallbackProtocol) {
    try {
      if (typeof target === 'string' || target instanceof URL) {
        const url = new URL(String(target));
        const port = url.port || (url.protocol === 'https:' || url.protocol === 'wss:' ? 443 : 80);
        return { scheme: url.protocol.replace(':', ''), host: url.hostname, port: Number(port) };
      }
      if (target && typeof target === 'object' && typeof target.url === 'string') {
        return endpoint(target.url, fallbackProtocol);
      }
      if (target && typeof target === 'object') {
        const scheme = (target.protocol || fallbackProtocol).replace(':', '');
        const host = target.hostname || target.host || 'localhost';
        const port = target.port || (scheme === 'https' ? 443 : 80);
        return { scheme, host: String(host).replace(/:\d+$/, ''), port: Number(port) };
      }
    } catch {
      // Fall through to an unnamed endpoint rather than lose the event.
    }
    return { scheme: fallbackProtocol, host: '?', port: 0 };
  }
  for (const [moduleName, scheme] of [
    ['node:http', 'http'],
    ['node:https', 'https'],
  ]) {
    const module = require(moduleName);
    for (const name of ['request', 'get']) {
      wrap(module, name, requests, (args) => {
        emit('request', `${scheme}.${name}`, endpoint(args[0], scheme));
      });
    }
  }
  wrap(globalThis, 'fetch', requests, (args) => {
    emit('request', 'fetch', endpoint(args[0], 'https'));
  });
  wrap(globalThis, 'WebSocket', requests, (args) => {
    emit('request', 'WebSocket', endpoint(args[0], 'wss'));
  });
  if (typeof Bun !== 'undefined') {
    wrap(Bun, 'fetch', requests, (args) => {
      emit('request', 'fetch', endpoint(args[0], 'https'));
    });
    wrap(Bun, 'connect', sockets, (args) => {
      const options = args[0] || {};
      emit('connect', 'Bun.connect', {
        family: options.unix ? 'unix' : 'inet',
        host: options.hostname,
        port: Number(options.port),
        tls: Boolean(options.tls),
      });
    });
  }

  // Name resolution.
  const names = { depth: 0 };
  const dns = require('node:dns');
  wrap(dns, 'lookup', names, (args) => emit('resolve', 'dns.lookup', { host: String(args[0]) }));
  wrap(dns.promises, 'lookup', names, (args) =>
    emit('resolve', 'dns.promises.lookup', { host: String(args[0]) }),
  );

  // Node binds an ES module's named imports of a builtin when it is first imported, so the
  // wrappers above reach `import { spawn } from 'node:child_process'` only after this sync.
  try {
    require('node:module').syncBuiltinESMExports();
  } catch {
    // Bun has no such step to take.
  }
})();
