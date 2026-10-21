import { createHash } from 'node:crypto';
import { existsSync, readFileSync } from 'node:fs';
import { relative, resolve } from 'node:path';
import { gunzipSync } from 'node:zlib';
import { afterAll, expect } from 'vitest';
import { recordedName } from './recorded-name';

/* What the previous interface said, recorded, so the React port stays held to it after that interface was
   removed. "Legacy" in this seam, in the `legacy*.test.helper.ts` files and in the differential tests means
   that removed page: its source is gone from the shipped plugin and nothing here reads it.

   Each differential test compares the TypeScript port with the recorded answers of the removed page over
   generated inputs. A harness (`legacyHarness`) is a stand-in for the removed page's functions: calling one
   of its methods looks the answer up in `frontend/test/golden/vitest/<test file>.json.gz`. These files are
   fixtures of record. The page that produced them no longer exists, so they cannot be regenerated; a changed
   generator, input or step fails with the name of the call that has no recorded answer. A deliberate
   departure from a recorded behaviour is an edit to the test that says so, and an entry in the design
   record, never a silent change of input.

   A key is a hash of what the removed page was asked: the harness, the method, its arguments and the state
   the earlier calls left it in. State is tracked as a hash and never read back from a page, so a method has
   to say how it changes state (see `HarnessSpec`). The state returns to where the module left it at the
   start of every test, so a test filtered by name asks for the same keys as it does in a full run.

   The generators stay deterministic (fixed seeds) so a run finds the keys that were recorded. How many cases
   each differential runs is a `CASES` constant in the test: the committed goldens hold a few dozen to a
   hundred generated cases per differential, plus the hand-built edge cases, because the migration's
   thousands of cases proved the port equal once and the goldens only have to keep it so. A rare state the
   first seeds miss is reached by a named witness seed (`seedSample`). A callback handed to the removed page
   stands in a key by its source text, so reformatting one changes the key. The goldens were checked against
   a clock moved 400 days on: nothing in them reads the wall clock.

   Every key a golden holds must be asked for by the end of its test file's run, so a removed or shortened
   differential (a smaller `CASES`, a dropped step) fails instead of leaving recorded answers nothing
   compares. A run that cannot reach them all says so: a name filter (`-t`) skips the check, and a file
   that skips tests on purpose calls `allowUnreadGoldens` with the reason.

   Answers are stored through one codec, so a test cannot pass against a value a golden could not hold. The
   codec keeps what a JSON round trip would hide (`undefined`, `NaN`, `-0`, the infinities, `Set`, `Map`,
   `Date`, `RegExp`) and refuses what it cannot keep (a function). */

/* ---- the codec ---- */

const SPECIAL = new Map<string, number>([
  ['NaN', Number.NaN],
  ['Infinity', Number.POSITIVE_INFINITY],
  ['-Infinity', Number.NEGATIVE_INFINITY],
  ['-0', -0],
]);

function tag(value: unknown): string {
  return Object.prototype.toString.call(value).slice(8, -1);
}

/* Fields the retired page never had. A recorded answer is keyed by the arguments it was given, so a field
   added since must not reach the key: the legacy code is handed the shape it was recorded against. */
const LATER_FIELDS = new Set(['ordinal', 'ordinalSub', 'ordinals', 'checkId']);

export function withoutLaterFields(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(withoutLaterFields);
  if (typeof value !== 'object' || value === null || tag(value) !== 'Object') return value;
  const out: Record<string, unknown> = {};
  for (const [key, item] of Object.entries(value)) {
    if (!LATER_FIELDS.has(key)) out[key] = withoutLaterFields(item);
  }
  return out;
}

/* `callbacks` is for an argument: a function the legacy code is handed (a label builder) cannot be stored, so
   its source stands for it in the key. It is never allowed in an answer. */
export function encode(value: unknown, callbacks = false): unknown {
  if (value === undefined) return { $: 'u' };
  if (value === null || typeof value === 'string' || typeof value === 'boolean') return value;
  if (typeof value === 'number') {
    if (Object.is(value, -0)) return { $: 'n', v: '-0' };
    if (!Number.isFinite(value)) return { $: 'n', v: String(value) };
    return value;
  }
  if (typeof value === 'function' && callbacks) return { $: 'fn', v: String(value) };
  if (typeof value !== 'object') {
    throw new Error(`A golden cannot hold a ${typeof value}.`);
  }
  switch (tag(value)) {
    case 'Array':
      return (value as unknown[]).map((item) => encode(item, callbacks));
    case 'Set':
      return { $: 'set', v: [...(value as Set<unknown>)].map((item) => encode(item, callbacks)) };
    case 'Map':
      return {
        $: 'map',
        v: [...(value as Map<unknown, unknown>)].map(([key, item]) => [
          encode(key, callbacks),
          encode(item, callbacks),
        ]),
      };
    case 'Date':
      return { $: 'date', v: (value as Date).getTime() };
    case 'RegExp':
      return { $: 're', v: (value as RegExp).source, f: (value as RegExp).flags };
    case 'Object': {
      const out: Record<string, unknown> = {};
      for (const [key, item] of Object.entries(value)) out[key] = encode(item, callbacks);
      // A plain object that already has a `$` key would read back as a tagged value.
      return '$' in out ? { $: 'o', v: out } : out;
    }
    default:
      throw new Error(`A golden cannot hold a ${tag(value)}.`);
  }
}

export function decode(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(decode);
  if (typeof value !== 'object' || value === null) return value;
  const record = value as Record<string, unknown>;
  const marker = record['$'];
  if (typeof marker === 'string') {
    switch (marker) {
      case 'u':
        return undefined;
      case 'n':
        return SPECIAL.get(String(record['v']));
      case 'set':
        return new Set((record['v'] as unknown[]).map(decode));
      case 'map':
        return new Map(
          (record['v'] as [unknown, unknown][]).map(([k, v]) => [decode(k), decode(v)]),
        );
      case 'date':
        return new Date(record['v'] as number);
      case 're':
        return new RegExp(record['v'] as string, record['f'] as string);
      case 'o':
        // The fields of a plain object that had a `$` key of its own: read each as a field, not as a tag.
        return Object.fromEntries(
          Object.entries(record['v'] as Record<string, unknown>).map(([key, item]) => [
            key,
            decode(item),
          ]),
        );
      default:
        throw new Error(`An unknown golden tag "${marker}".`);
    }
  }
  const out: Record<string, unknown> = {};
  for (const [key, item] of Object.entries(record)) out[key] = decode(item);
  return out;
}

function digest(text: string): string {
  return createHash('sha1').update(text).digest('hex').slice(0, 12);
}

/* ---- the golden file of one test file ---- */

interface GoldenFile {
  readonly v: 1;
  /** key -> result digest. */
  readonly entries: Record<string, string>;
  /** result digest -> encoded result; one copy however many keys answer with it. */
  readonly results: Record<string, unknown>;
  /** digest -> a large subtree or string that results share, so a window that grows by one row costs one row. */
  readonly blobs: Record<string, unknown>;
}

function expand(node: unknown, blobs: ReadonlyMap<string, unknown>): unknown {
  if (Array.isArray(node)) return node.map((item) => expand(item, blobs));
  if (typeof node !== 'object' || node === null) return node;
  const record = node as Record<string, unknown>;
  if (record['$'] === 'ref') {
    const id = String(record['h']);
    if (!blobs.has(id)) throw new Error(`The golden file lacks the shared value ${id}.`);
    return expand(blobs.get(id), blobs);
  }
  const out: Record<string, unknown> = {};
  for (const [key, item] of Object.entries(record)) out[key] = expand(item, blobs);
  return out;
}

const GOLDEN_DIR = 'frontend/test/golden/vitest';

function testFile(): string {
  const worker = (globalThis as { __vitest_worker__?: { filepath?: string } }).__vitest_worker__;
  const path = worker?.filepath ?? expect.getState().testPath;
  if (!path) throw new Error('The golden seam could not tell which test file it serves.');
  return path;
}

function goldenPath(): string {
  const name = relative(resolve(process.cwd(), 'frontend/src'), testFile())
    .replaceAll('\\', '/')
    .replaceAll('/', '__');
  return resolve(process.cwd(), GOLDEN_DIR, `${name}.json.gz`);
}

class Goldens {
  private readonly entries = new Map<string, string>();
  private readonly results = new Map<string, unknown>();
  private readonly blobs = new Map<string, unknown>();
  private loaded = false;

  private load(): void {
    if (this.loaded) return;
    this.loaded = true;
    const path = goldenPath();
    if (!existsSync(path)) return;
    const file = JSON.parse(gunzipSync(readFileSync(path)).toString('utf8')) as GoldenFile;
    for (const [key, id] of Object.entries(file.entries)) this.entries.set(key, id);
    for (const [id, blob] of Object.entries(file.blobs)) this.blobs.set(id, blob);
    for (const [id, result] of Object.entries(file.results))
      this.results.set(id, expand(result, this.blobs));
  }

  private readonly asked = new Set<string>();

  /** The recorded answer, as the codec holds it. */
  answer(key: string): string | undefined {
    this.load();
    const id = this.entries.get(key);
    if (id !== undefined) this.asked.add(key);
    return id === undefined ? undefined : JSON.stringify(this.results.get(id));
  }

  /** The recorded keys nothing asked for. */
  unasked(): string[] {
    this.load();
    return [...this.entries.keys()].filter((key) => !this.asked.has(key));
  }

  describe(): string {
    return relative(process.cwd(), goldenPath());
  }
}

const goldens = new Goldens();

let unreadAllowed = '';

/** A test file that skips tests on purpose, or that records more than it can ask for, says why here, once. */
export function allowUnreadGoldens(reason: string): void {
  if (!reason.trim())
    throw new Error('allowUnreadGoldens needs the reason the golden is not read in full.');
  unreadAllowed = reason;
}

function filtered(): boolean {
  const worker = (globalThis as { __vitest_worker__?: { config?: { testNamePattern?: unknown } } })
    .__vitest_worker__;
  return Boolean(worker?.config?.testNamePattern);
}

// Registered at import, which happens while the test file is collected: a hook may not be added from a test.
afterAll(() => {
  if (unreadAllowed || filtered()) return;
  const unread = goldens.unasked();
  if (unread.length)
    throw new Error(
      `${String(unread.length)} recorded answer(s) in ${goldens.describe()} were never asked for: ${unread.slice(0, 3).join(', ')}. A generator, a step or a case count shrank; the page that recorded them is gone, so restore the case or say why with allowUnreadGoldens.`,
    );
});

/* ---- the wrapper ---- */

/** How a harness method treats the legacy page's state. A method not named is `append`. */
export interface HarnessSpec {
  /** Answers depend on the arguments alone (a pure method may also name a slot it overwrites). */
  readonly pure?: readonly string[];
  /** Answers depend on the state and leave it as it was. */
  readonly observe?: readonly string[];
  /** Replaces one named piece of state (`setData` replaces the data), whatever came before. */
  readonly slots?: Readonly<Record<string, string>>;
  /** Returns the page to its first state. */
  readonly reset?: readonly string[];
  /** Properties that read as a snapshot of the page's state. */
  readonly props?: readonly string[];
  /** Methods that return a promise. */
  readonly async?: readonly string[];
}

function currentTest(): string | undefined {
  return expect.getState().currentTestName;
}

/** A stand-in for the removed page's functions, one per `kind`. Every method call and every `props` read is
 *  answered from the golden of the test file that asks; none runs any code. */
export function legacyHarness<T extends object>(kind: string, spec: HarnessSpec = {}): T {
  const baseline = { chain: 'first', slots: {} as Record<string, string> };
  let chain = baseline.chain;
  let slots: Record<string, string> = {};
  let lastTest: string | undefined;

  const arrive = (): void => {
    const test = currentTest();
    if (test === lastTest) return;
    lastTest = test;
    // What setup left (module-level calls) is the state every test starts from.
    if (test !== undefined) {
      chain = baseline.chain;
      slots = { ...baseline.slots };
    }
  };
  const rebase = (): void => {
    if (currentTest() === undefined) {
      baseline.chain = chain;
      baseline.slots = { ...slots };
    }
  };
  const state = (): string =>
    digest(`${chain}|${JSON.stringify(slots, Object.keys(slots).sort())}`);

  const keyFor = (name: string, args: string, stateful: boolean): string =>
    digest(`${kind}|${name}|${args}|${stateful ? state() : ''}`);

  const answer = <R>(key: string, label: string): R => {
    const stored = goldens.answer(key);
    if (stored === undefined)
      throw new Error(
        `No golden for ${kind}.${label} in ${goldens.describe()}. A generator, an input or a step changed, and the page that recorded the answers no longer exists.`,
      );
    return decode(recordedName(JSON.parse(stored))) as R;
  };

  const pure = new Set(spec.pure);
  const observeOnly = new Set(spec.observe);
  const reset = new Set(spec.reset);
  const props = new Set(spec.props);
  const asyncMethods = new Set(spec.async);

  const invoke = (name: string, args: unknown[]): unknown => {
    arrive();
    const encodedArgs = JSON.stringify(recordedName(encode(withoutLaterFields(args), true), true));
    const isPure = pure.has(name);
    const key = keyFor(name, encodedArgs, !isPure);
    const result = answer(key, name);
    const slot = spec.slots?.[name];
    if (reset.has(name)) {
      chain = baseline.chain;
      slots = { ...baseline.slots };
    } else if (slot !== undefined) slots = { ...slots, [slot]: digest(encodedArgs) };
    else if (isPure || observeOnly.has(name))
      return asyncMethods.has(name) ? Promise.resolve(result) : result;
    else chain = digest(`${chain}|${name}|${encodedArgs}`);
    rebase();
    return asyncMethods.has(name) ? Promise.resolve(result) : result;
  };

  const snapshot = (name: string): unknown => {
    arrive();
    return answer(keyFor(`prop:${name}`, '', true), `prop ${name}`);
  };

  return new Proxy({} as T, {
    get(_target, property) {
      if (typeof property !== 'string') return undefined;
      if (property === 'then') return undefined;
      if (props.has(property)) return snapshot(property);
      return (...args: unknown[]) => invoke(property, args);
    },
  });
}

/** A differential's generated cases: the seeds 1..`cases`, then the `witnesses`, one seed each for a rare
 *  state the first seeds do not reach, found once by running the generator wide. Keeping them as named seeds
 *  lets the committed record stay small without losing the states the "agreement proves something" checks
 *  demand. */
export function seedSample(cases: number, witnesses: readonly number[] = []): number[] {
  const seeds = Array.from({ length: cases }, (_, index) => index + 1);
  for (const witness of witnesses)
    if (witness > cases && !seeds.includes(witness)) seeds.push(witness);
  return seeds;
}
