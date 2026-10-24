import { describe, expect, it } from 'vitest';
import { createAnnouncer } from '../shell/announcer';
import { createFakeClock } from '../transport/testing';
import { annotationOf } from '../intent/annotation';
import type { DraftInput } from '../intent/derive';
import { createHeld } from '../intent/held';
import { genSession, mulberry32, pick, type Rng } from '../intent/generate.test.helper';
import { canonical, firstDifference } from '../observed/legacy.test.helper';
import { loadLegacyDrift } from './legacy.test.helper';
import {
  capReset,
  eligibility,
  policyReason,
  pressRefusal,
  promptReadingRefusal,
  readingJob,
  readingRefusal,
  readingRoute,
  readingStates,
  routeRefusal,
  withheldAge,
} from './route';

/* Who would read a session, whether they may, and what refuses a press, run next to the legacy page over
   generated payloads. The three refusals that rank above every other are asserted by name as well, because
   a ranking that agrees on average can still be wrong where it matters. */
const legacy = loadLegacyDrift();
legacy.lift([
  'NEXT_READING_SAVE_STEP',
  'NEXT_READING_NO_WORDS',
  'NEXT_READING_MODEL_UNREAD',
  'NEXT_READING_MODEL_OFF',
  'NEXT_READING_UNAUTHORIZED',
  'NEXT_READING_ANNOTATIONS_OFF',
  'NEXT_READING_ROUTE_UNREAD',
  'NEXT_READING_AGENT_WORDS_HARNESSES',
  'nextCockpitReadingRequests',
  'nextReadingRoute',
  'nextReadingConsent',
  'nextReadingToolOutputGranted',
  'nextReadingNeedsAllow',
  'NEXT_READING_PRESS_LINES',
  'NEXT_READING_PRESS_CODEX',
  'NEXT_READING_PRESS_CLAUDE',
  'NEXT_READING_PRESS_EVENTS',
  'nextReadingEligibility',
  'nextReadingPressLine',
  'nextReadingPressRefusal',
  'nextReadingWithheldAge',
  'nextReadingAnyConsent',
  'nextReadingRouteRefusal',
  'nextReadingPolicyReason',
  'nextReadingJob',
  'nextReadingBudgetLine',
  'nextCockpitReadingStates',
  'nextCockpitReadingRefusal',
  'NEXT_INTENT_EDITED',
  'NEXT_INTENT_SAVING',
  'nextCockpitIntentKey',
  'nextIntentEditedRefusal',
  'nextImplicitAdoption',
  'nextPromptReadingRefusal',
]);
legacy.lift(['fmtDur'], 'next-cockpit-compat.js');

const CASES = 80;
const SEEDS = CASES;

function genPayload(rnd: Rng): Record<string, unknown> {
  const policy = pick(rnd, [
    undefined,
    null,
    { consent: true },
    { consent: false },
    { providers: { claude: true, codex: false }, tool_output: { claude: ['api'] } },
    { providers: { claude: false }, words: { claude: true }, tool_output: { claude: ['x'] } },
    { reason: 'run-disabled' },
    { reason: 'store-unavailable' },
    { reason: 'daily-cap', retry_at: 1_800_000_000 },
    { reason: 'daily-cap' },
    { reason: 'consent-required', used: 3, limit: 10 },
    { used: 12, limit: 10 },
    { used: 'x', limit: 10 },
  ]);
  const route = pick(rnd, [
    undefined,
    { provider: 'claude', harness: 'claude', destination: 'api', model: 'm' },
    { provider: 'codex', harness: 'codex', destination: '' },
    { provider: '', note: 'No reader on this machine.' },
    { provider: '', note: '' },
    { provider: 'claude', harness: 'claude', destination: 'other' },
  ]);
  return {
    generated: 1000,
    annotate: pick(rnd, [true, true, true, false]),
    annotate_unreadable: pick(rnd, ['', '', '', 'The store could not be read.']),
    annotate_discard: pick(rnd, [{ unreadable: 'Discarded.' }, {}, undefined]),
    reading_check: pick(rnd, ['passed', 'accepted', 'failed', undefined]),
    ...(policy === undefined ? {} : { reading: policy }),
    reading_routes: route === undefined ? undefined : { claude: route, codex: route },
    reading_jobs: pick(rnd, [undefined, {}, 'x']),
  };
}

function genRow(rnd: Rng, index: number): Record<string, unknown> {
  const base = genSession(rnd, index);
  return {
    ...base,
    harness: pick(rnd, ['claude', 'codex', 'pi']),
    first_prompt: pick(rnd, ['Fix the redirect', '', 'Ship it']),
    first_prompt_at: pick(rnd, [800, 0, null]),
    first_prompt_control: pick(rnd, [true, false, undefined]),
    prompt_states_work: pick(rnd, [true, false, undefined]),
    prompt_at: pick(rnd, [900, null]),
    title: pick(rnd, ['Latest ask', '', null]),
    instruction: pick(rnd, [{ label: 'asked', text: 'Asked words', at: 905 }, null, undefined]),
    acquisition: pick(rnd, ['event', 'scan', undefined]),
    reading_eligibility: pick(rnd, [
      undefined,
      { ok: false, reason: 'idle-unknown', sentence: 'Server says so.' },
      { ok: false, reason: 'settling', until: 9e12, sentence: 'Settling.' },
      { ok: false, reason: 'settling', until: 1, sentence: 'Settled.' },
      { ok: false, reason: 'turn-stop', sentence: 'A stop.' },
      { ok: false, reason: 'revision-after-end', sentence: 'After end.' },
      { ok: false, reason: 'novel', sentence: 'A novel reason.' },
      { ok: true },
      { ok: false },
    ]),
    annotation_reading_withheld_at: pick(rnd, [990, 900, 1000, undefined, 0]),
  };
}

describe('the route and unchanged refusals read as the legacy page reads them', () => {
  it(`agree on ${String(SEEDS)} generated payloads and sessions`, () => {
    const failures: string[] = [];
    const seen: Record<string, number> = {};
    const note = (name: string) => {
      seen[name] = (seen[name] ?? 0) + 1;
    };
    for (let seed = 1; seed <= SEEDS && failures.length < 3; seed += 1) {
      const rnd = mulberry32(seed + 77);
      const session = genRow(rnd, seed);
      const payload = genPayload(rnd);
      const answered = pick(rnd, [
        undefined,
        { eligibility: { ok: false, reason: 'settling', until: 9e12, sentence: 'Held.' } },
        { eligibility: { ok: false, reason: 'idle-unknown', sentence: 'x' } },
      ]);
      const key = `${String(session['harness'])}:${String(session['sid'])}`;
      legacy.setData(payload);
      legacy.run('nextCockpitReadingRequests.clear();');
      if (answered)
        legacy.run('nextCockpitReadingRequests.set(__k, __v);', { k: key, v: answered });
      const annotation = annotationOf(session as never);
      const clock = createFakeClock();
      const held = createHeld({ clock, announcer: createAnnouncer() });
      const input: DraftInput = {
        held,
        contexts: new Map(),
        payload: payload as never,
        session: session as never,
        annotation,
      };
      const route = readingRoute(payload as never, session as never);
      /* Deviation: the spent budget is worded as the session page's banner words it, with the reset as a
         local time rather than a full date. */
      const policy = payload['reading'] as Record<string, unknown> | null | undefined;
      const retry = typeof policy?.['retry_at'] === 'number' ? policy['retry_at'] : null;
      const capped = (text: string) =>
        text
          .replace(
            'The daily reading limit is reached. Wait for the next update.',
            'Analysis limit reached. Wait for the next update.',
          )
          .replace(
            /The daily reading limit is reached\. Try again after [^.]*\./,
            retry === null
              ? ''
              : `Analysis limit reached. You can analyze again at ${capReset(retry, Date.now())}.`,
          );
      const same = (name: string, theirs: unknown, mine: unknown) => {
        const found = firstDifference(
          canonical(
            typeof theirs === 'string'
              ? capped(
                  /* Deviation (owner, 2026-10-20): Claude Code has no idle line of its own, since an
                     idle Claude Code session is read rather than refused; a stale idle token falls to
                     the line every harness gets. */
                  theirs.replace(
                    "Last turn isn't recorded as finished. Run another turn to open Analyze.",
                    session['acquisition'] === 'event'
                      ? 'Analyze opens while this session runs or once it ends.'
                      : 'Analyze opens while this session runs.',
                  ),
                )
              : theirs,
          ),
          canonical(mine),
        );
        if (found) failures.push(`seed ${String(seed)} ${name}: ${found}`);
      };
      same('route', legacy.call('nextReadingRoute', session), route);
      const provider = route && route['provider'] ? String(route['provider']) : '';
      /* These four recorded admission answers predate the owner’s opt-out ruling (2026-10-19).
         Keep the oracle calls in sequence; they no longer describe a reader-started press.
         [The widening](../../../docs/design-session-summary.md#the-widening-opt-out-with-a-notice-for-every-call-a-reader-starts) */
      legacy.call('nextReadingConsent', provider, String(session['harness']));
      legacy.call('nextReadingToolOutputGranted', route);
      legacy.call('nextReadingNeedsAllow', route);
      legacy.call('nextReadingAnyConsent');
      same(
        'eligibility',
        legacy.call('nextReadingEligibility', session),
        eligibility(session as never, answered, Date.now()),
      );
      same(
        'press refusal',
        legacy.call('nextReadingPressRefusal', session),
        pressRefusal(session as never, answered, Date.now()),
      );
      same(
        'withheld age',
        legacy.call('nextReadingWithheldAge', annotation),
        withheldAge(annotation, 1000),
      );
      same(
        'route refusal',
        legacy.call('nextReadingRouteRefusal', session),
        routeRefusal(payload as never, session as never),
      );
      same(
        'policy',
        legacy.call('nextReadingPolicyReason', payload['reading']),
        policyReason(payload['reading']),
      );
      same(
        'job',
        legacy.call('nextReadingJob', session),
        readingJob(payload as never, session as never),
      );
      /* The budget line is no longer drawn: the spent budget is the session page's banner, and under the cap
         nothing is said. The legacy call stays in the recorded sequence, which chains every call. */
      legacy.call<string>('nextReadingBudgetLine');
      same(
        'states',
        legacy.call('nextCockpitReadingStates', annotation, null),
        readingStates(payload as never, annotation),
      );
      same(
        'refusal',
        legacy.call('nextCockpitReadingRefusal', annotation, null),
        readingRefusal(payload as never, annotation),
      );
      for (const saving of [false, true]) {
        legacy.run(
          saving ? 'nextPending.set("intent:" + __k + ":save", 1);' : 'nextPending.clear();',
          { k: key },
        );
        // The legacy page reads its own intent key, so ask it for the key it would hold.
        const intentKey = legacy.call<string>('nextCockpitIntentKey', session);
        legacy.run('nextPending.clear(); if(__s) nextPending.set(__key + ":save", 1);', {
          s: saving,
          key: intentKey,
        });
        const theirs = legacy.call<string>('nextPromptReadingRefusal', session, annotation, null);
        const mine = promptReadingRefusal({ input, saving, answered, nowMs: Date.now() });
        same(`prompt refusal (saving ${String(saving)})`, theirs, mine);
        note(`refusal:${mine ? mine.slice(0, 24) : 'none'}`);
        const heldLive = legacy.call<string>(
          'nextPromptReadingRefusal',
          session,
          annotation,
          null,
          true,
        );
        same(
          'held-live refusal',
          heldLive,
          promptReadingRefusal({ input, saving, answered, nowMs: Date.now() }, true),
        );
      }
    }
    expect(failures).toEqual([]);
    // The ranking reaches an empty refusal and several different ones, or the comparison proves little.
    expect(Object.keys(seen).length).toBeGreaterThan(5);
    expect(seen['refusal:none'] ?? 0).toBeGreaterThan(0);
  });
});
