// @vitest-environment node
/* The reasons a route can give a session and the phases a running reading publishes, held between the
   producer and the stories. `reading_route.REASONS` is the closed set the server publishes as
   `reading_routes[harness].reason`, and `reading.PHASES` and `reading.PHASE_TEXT` are the steps of a running
   analysis. `drift.reasons.ts` holds a route fixture for each reason and `drift.scenario.tsx` the job, and
   `Drift.stories.tsx` exports one story per reason. A reason added to the producer without a fixture and a
   story, or a phase renamed or reworded, fails here.

   The producer's values are the real ones: the test imports the Python modules and prints them as JSON, so a
   source layout this file cannot parse (a second `REASONS +=`, a tuple built elsewhere) cannot make it agree
   with a stale list. A Python it cannot run is a failure and never a skip, because a guard that skips on a
   machine without Python guards nothing there. Both CI jobs that run `pnpm test` have Python 3.12 on PATH
   (`quality-gate.yml` Frontend, `release.yml` verify-frontend); `COMPASS_TEST_PYTHON` names another, as the
   development-supervisor tests do. The stories are read from the module's own exports, so one that is
   removed or commented out is not counted. Every reason reaches the page with its own copy: a reason with no
   reader replaces Analyze with its note, and one with a reader says why that reader in "What is sent", so
   none is exempt. */
import { execFileSync } from 'node:child_process';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';
import * as drift from './Drift.stories';
import { REASON_CASES, routeFor } from './drift.reasons';
import { JOB, JOB_STEPS } from './drift.scenario';

const plugin = fileURLToPath(new URL('../../compass/skills/compass', import.meta.url));
const routeSource = readFileSync(
  new URL('../../compass/skills/compass/compass_runtime/reading_route.py', import.meta.url),
  'utf8',
);

interface Producer {
  readonly reasons: string[];
  readonly phases: string[];
  readonly phaseText: Record<string, string>;
}

const PROGRAM = [
  'import json, sys',
  'sys.path.insert(0, sys.argv[1])',
  'from compass_runtime import reading, reading_route',
  'print(json.dumps({"reasons": list(reading_route.REASONS), "phases": list(reading.PHASES),',
  ' "phaseText": dict(reading.PHASE_TEXT)}))',
].join('\n');

function producer(): Producer {
  const python =
    process.env['COMPASS_TEST_PYTHON'] || (process.platform === 'win32' ? 'python' : 'python3');
  try {
    const out = execFileSync(python, ['-I', '-c', PROGRAM, plugin], {
      encoding: 'utf8',
      timeout: 60_000,
      stdio: ['ignore', 'pipe', 'pipe'],
      env: { ...process.env, PYTHONDONTWRITEBYTECODE: '1' },
    });
    return JSON.parse(out) as Producer;
  } catch (error) {
    throw new Error(
      `Could not read the producer's reasons and phases with ${python}: ${String(error)}. ` +
        'This guard needs Python 3.12+ (set COMPASS_TEST_PYTHON to name one); it does not skip.',
      { cause: error },
    );
  }
}

const sorted = (values: Iterable<string>): string[] => [...values].sort();
const python = producer();

/* A story that publishes a route, with the reason that route carries. */
const reasonsStoried = Object.values(drift).flatMap((story) => {
  const route = (story as { args?: { scenario?: { route?: { reason?: unknown } } } }).args?.scenario
    ?.route;
  return typeof route?.reason === 'string' ? [{ reason: route.reason, story }] : [];
});

describe('the route reasons the stories cover', () => {
  it('reads a producer list it can use', () => {
    expect(python.reasons.length).toBeGreaterThanOrEqual(8);
    expect(new Set(python.reasons).size).toBe(python.reasons.length);
  });

  it('are the reasons the producer can publish, no more and no fewer', () => {
    expect(sorted(Object.keys(REASON_CASES))).toEqual(sorted(python.reasons));
  });

  it('each have an exported story that plays, and no story is for another', () => {
    expect(sorted(reasonsStoried.map((found) => found.reason))).toEqual(sorted(python.reasons));
    for (const { story } of reasonsStoried) {
      expect(typeof (story as { play?: unknown }).play).toBe('function');
    }
  });

  it('publish a route whose reader is named exactly when the fixture says it has one', () => {
    for (const [reason, found] of Object.entries(REASON_CASES)) {
      const route = routeFor(reason);
      expect(route['reason']).toBe(reason);
      expect(route['provider']).toBe(found.provider);
      expect(Boolean(route['disclosure'])).toBe(found.provider !== '');
    }
  });

  it('word each note as the producer does', () => {
    for (const fragment of [
      "This session's own harness reads it.",
      'This harness has no reading producer of its own',
      'checks are not qualified on this build',
      'CLI was not found on this machine',
      ', so no analysis can run for this session.',
      ', so {LABELS[other]} reads this session.',
    ]) {
      expect(routeSource, fragment).toContain(fragment);
    }
  });
});

describe('the running analysis the Analyzing story draws', () => {
  it('has the phases the producer publishes, in its order, worded as it words them', () => {
    expect(JOB_STEPS.map((step) => step.phase)).toEqual(python.phases);
    expect(JOB_STEPS.map((step) => step.text)).toEqual(
      python.phases.map((phase) =>
        (python.phaseText[phase] ?? '').replace('{label}', 'Claude Code'),
      ),
    );
    expect(python.phases).toContain(JOB.phase);
  });
});
