// @vitest-environment jsdom
import { describe, expect, it } from 'vitest';
import { compatSessKey } from '../api/identity';
import type { ContextEntry } from '../store/board';
import { createAnnouncer } from '../shell/announcer';
import { createFakeClock } from '../transport/testing';
import { canonical, firstDifference } from '../observed/legacy.test.helper';
import { annotationLines, annotationOf } from './annotation';
import {
  adoption,
  chosenCandidate,
  chosenIsStale,
  chosenOverSaved,
  directionLinesQuestion,
  directionWhy,
  goalBaseline,
  goalKey,
  heldKey,
  intentChanges,
  intentDraft,
  intentDrafted,
  intentUnsaved,
  linesChanged,
  linesDraft,
  linesKey,
  lineSource,
  noDraftWhy,
  promptChoices,
  promptClip,
  promptMenu,
  type DraftInput,
} from './derive';
import { createHeld } from './held';
import { mulberry32, pick, genSession, type Rng } from './generate.test.helper';
import { loadLegacyIntent } from './legacy.test.helper';
import { workSource } from './work';
import { seedSample } from '../../test/legacy_goldens';

/* The Intent panel's derivations, run next to the legacy functions over generated sessions, payloads,
   contexts and held state. What the reader typed, picked and chose is the state a redraw must keep, so the
   comparison is made with that state present and absent, over drafts, chosen prompts and menu lists.

   One difference is by design and is checked as a pair: the legacy `nextIntentDraft` deletes a held choice
   that no longer stands, from inside the read; `intentDraft` is pure and `chosenIsStale` says the same
   thing, so the test asserts the legacy page deleted exactly when this one says it is stale. */
const legacy = loadLegacyIntent();
const CASES = 60;
// The first seed that reaches a chosen prompt in the menu.
const WITNESSES = [150];
const SAMPLE = seedSample(CASES, WITNESSES);
const SEEDS = SAMPLE.length;

const PROMPTS = ['Fix the redirect', 'Ship the queue', 'Tidy the labels', 'x'.repeat(300), ''];

function genHarnessSession(rnd: Rng, index: number): Record<string, unknown> {
  const base = genSession(rnd, index);
  const first = pick(rnd, PROMPTS);
  return {
    ...base,
    harness: pick(rnd, ['claude', 'codex', 'pi', 'claude']),
    first_prompt: first,
    first_prompt_at: pick(rnd, [800, 0, null, 850]),
    first_prompt_control: pick(rnd, [true, false, undefined]),
    prompt_states_work: pick(rnd, [true, false, undefined]),
    prompt_at: pick(rnd, [900, null]),
    title: pick(rnd, ['Latest ask', '', null]),
    instruction: pick(rnd, [
      { label: 'asked', text: 'The asked words', at: 905 },
      { label: 'agent', text: 'agent said', at: 906 },
      null,
      undefined,
    ]),
    copied_prompts: pick(rnd, [
      [{ quoted_as: ['first_prompt'] }],
      [{ quoted_as: ['instruction'] }],
      [],
      undefined,
    ]),
    annotation_revision: pick(rnd, [0, 1, 3, null]),
  };
}

interface Case {
  readonly session: Record<string, unknown>;
  readonly payload: Record<string, unknown>;
  readonly contexts: Map<string, ContextEntry>;
  readonly state: {
    readonly goal: string | undefined;
    readonly lines: string[] | undefined;
    readonly origins: (number | null)[] | undefined;
    readonly chosen: Record<string, unknown> | undefined;
    readonly menu: Record<string, unknown> | undefined;
    readonly direction: Record<string, unknown> | undefined;
  };
}

function genCase(seed: number): Case {
  const rnd = mulberry32(seed);
  const session = genHarnessSession(rnd, seed);
  const payload = {
    annotate: pick(rnd, [true, true, true, false]),
    annotate_unreadable: pick(rnd, ['', '', '', 'The store could not be read.']),
    annotate_cap: pick(rnd, [undefined, undefined, 12, 240]),
    generated: 1000,
  };
  const offered = [
    { fact_id: 'p1', text: 'Fix the redirect', at: 800, cut: false },
    { fact_id: 'p2', text: 'Ship the queue', at: 850, cut: true },
    { fact_id: '', text: 'no id', at: 860 },
    { fact_id: 'p3', text: '  ', at: 870 },
    { fact_id: 'p4', text: 'no time', at: 0 },
  ];
  const contexts = new Map<string, ContextEntry>();
  if (rnd() < 0.7) {
    const data = {
      prompt_choices:
        rnd() < 0.8 ? offered.slice(0, 1 + Math.floor(rnd() * offered.length)) : undefined,
    };
    contexts.set(`/repo\n${compatSessKey(session as never)}`, {
      data: data as never,
      revision: 1,
      error: rnd() < 0.2 ? { kind: 'network-error' } : null,
    });
  }
  const goalPool = ['Ship the queue', 'typed words', '', 'Fix the redirect', 'a'.repeat(250)];
  const chosenPool = [
    { factId: 'p1', text: 'Fix the redirect', at: 800 },
    { factId: 'p2', text: 'Ship the queue', at: 850 },
    { factId: 'p9', text: 'gone', at: 900 },
    { factId: 'd1', text: 'A direction', at: 910, cut: true, direction: true, linesAnswer: null },
    {
      factId: 'd2',
      text: 'Another direction',
      at: 920,
      cut: false,
      direction: true,
      linesAnswer: 'keep',
    },
  ];
  return {
    session,
    payload,
    contexts,
    state: {
      goal: rnd() < 0.5 ? pick(rnd, goalPool) : undefined,
      lines:
        rnd() < 0.4 ? pick(rnd, [[], [''], ['one'], ['one', 'two'], ['a', '  ', 'c']]) : undefined,
      origins: undefined,
      chosen: rnd() < 0.4 ? pick(rnd, chosenPool) : undefined,
      menu:
        rnd() < 0.25
          ? {
              pending: false,
              open: false,
              choices: pick(rnd, [
                [{ factId: 'p1', text: 'Fix the redirect', at: 800, cut: false }],
                [],
                [{ factId: 'p2', text: 'Ship the queue', at: 850, cut: true }],
              ]),
            }
          : undefined,
      direction:
        rnd() < 0.3
          ? pick(rnd, [
              { factId: 'd1', n: 1, later: true, text: 'Do it', replace: null },
              { factId: 'd1', n: null, later: false, text: 'x'.repeat(300), replace: 2 },
            ])
          : undefined,
    },
  };
}

function load(input: Case): void {
  legacy.setData(input.payload);
  const sessKey = compatSessKey(input.session as never);
  legacy.run(
    `(() => { nextCockpitHeldDrafts.clear(); nextCockpitHeldOrigins.clear(); nextIntentChosenPrompts.clear();
     nextIntentPromptLists.clear(); nextCockpitDirectionLines.clear(); nextCockpitContexts.clear();
     const __k = nextCockpitHeldKey(__session, "goal"); const __l = nextCockpitHeldKey(__session, "lines");
     if(__state.goal !== undefined) nextCockpitHeldDrafts.set(__k, __state.goal);
     if(__state.lines !== undefined) nextCockpitHeldDrafts.set(__l, __state.lines.slice());
     if(__state.chosen !== undefined) nextIntentChosenPrompts.set(__k, Object.assign({}, __state.chosen));
     if(__state.menu !== undefined) nextIntentPromptLists.set(__skey, Object.assign({}, __state.menu));
     if(__state.direction !== undefined) nextCockpitDirectionLines.set(__skey, Object.assign({}, __state.direction));
     for(const [key, entry] of __contexts) nextCockpitContexts.set(key, {data: entry.data, revision: entry.revision, error: entry.error ? true : undefined}); })();`,
    {
      session: input.session,
      state: input.state,
      skey: sessKey,
      contexts: [...input.contexts],
    },
  );
}

function mine(input: Case) {
  const held = createHeld({ clock: createFakeClock(), announcer: createAnnouncer() });
  const { session, state } = input;
  if (state.goal !== undefined) held.goals.set(goalKey(session), state.goal);
  if (state.lines !== undefined) held.lines.set(linesKey(session), state.lines.slice());
  if (state.chosen !== undefined)
    held.chosen.set(goalKey(session), Object.assign({}, state.chosen) as never);
  if (state.menu !== undefined)
    held.prompts.set(compatSessKey(session as never), Object.assign({}, state.menu) as never);
  if (state.direction !== undefined)
    held.directions.set(
      compatSessKey(session as never),
      Object.assign({}, state.direction) as never,
    );
  const draft: DraftInput = {
    held,
    contexts: input.contexts,
    payload: input.payload,
    session,
    annotation: annotationOf(session),
  };
  return { held, draft };
}

describe('the Intent derivations agree with the legacy page over generated state', () => {
  it(`on ${String(SEEDS)} seeds, draft, choice, changes and refusals`, () => {
    const failures: string[] = [];
    const seen: Record<string, number> = {};
    const note = (name: string) => {
      seen[name] = (seen[name] ?? 0) + 1;
    };
    for (const seed of SAMPLE) {
      if (failures.length >= 3) break;
      const input = genCase(seed);
      load(input);
      const { held, draft } = mine(input);
      const { session, annotation } = draft;
      const checks: [string, unknown, unknown][] = [];
      checks.push([
        'choices',
        promptChoices(held, input.contexts, session),
        legacy.call('nextIntentPromptChoices', session),
      ]);
      checks.push([
        'chosenCandidate',
        chosenCandidate(held, input.contexts, session),
        legacy.call('nextPromptCandidate', session, 'chosen-prompt'),
      ]);
      const stale = chosenIsStale(draft);
      const had = held.chosen.has(goalKey(session));
      // Pure first: the legacy read below deletes a stale choice, and this one must say so beforehand.
      const mineDraft = intentDraft(draft);
      checks.push(['draft', mineDraft, legacy.call('nextIntentDraft', session, annotation)]);
      const lost = legacy.run<boolean>(
        'nextIntentChosenPrompts.has(nextCockpitHeldKey(__session, "goal"))',
        {
          session,
        },
      );
      checks.push(['stale', had && stale, had && !lost]);
      if (stale) note('stale');
      // The legacy read deleted the stale choice; the panel does the same after its render.
      if (stale) held.chosen.delete(goalKey(session));
      checks.push([
        'baseline',
        goalBaseline(draft),
        legacy.call('nextCockpitGoalBaseline', session, annotation),
      ]);
      checks.push([
        'over saved',
        chosenOverSaved(draft),
        legacy.call('nextIntentChosenOverSaved', session, annotation),
      ]);
      checks.push([
        'drafted',
        intentDrafted(draft),
        legacy.call('nextIntentDrafted', session, annotation),
      ]);
      checks.push([
        'unsaved',
        intentUnsaved(draft),
        legacy.call('nextIntentUnsaved', session, annotation),
      ]);
      checks.push([
        'changes',
        intentChanges(draft),
        legacy.call('nextCockpitIntentChanges', session, annotation),
      ]);
      checks.push([
        'adoption',
        adoption(mineDraft),
        legacy.call('nextIntentAdoption', legacy.call('nextIntentDraft', session, annotation)),
      ]);
      checks.push([
        'no draft why',
        noDraftWhy(session, annotation, input.payload),
        legacy.call('nextIntentNoDraftWhy', session, annotation),
      ]);
      checks.push([
        'lines draft',
        linesDraft(held, session, annotation),
        legacy.call('nextCockpitLinesDraft', session, annotation),
      ]);
      checks.push([
        'lines changed',
        linesChanged(linesDraft(held, session, annotation), annotation),
        legacy.call(
          'nextCockpitLinesChanged',
          legacy.call('nextCockpitLinesDraft', session, annotation),
          annotation,
        ),
      ]);
      checks.push([
        'lines question',
        directionLinesQuestion(held, session),
        Boolean(legacy.call<string>('nextDirectionLinesQuestion', session)),
      ]);
      const direction = held.directions.get(compatSessKey(session as never));
      if (direction && typeof direction.text === 'string') {
        const cap = legacy.run<number>('nextCockpitHeldCap()');
        checks.push([
          'direction why',
          directionWhy(direction, draft, cap),
          legacy.call(
            'nextCockpitDirectionWhy',
            legacy.run('nextCockpitDirectionLines.get(__skey)', {
              skey: compatSessKey(session as never),
            }),
            annotation,
            cap,
            session,
          ),
        ]);
        if (directionWhy(direction, draft, cap)) note('direction refused');
      }
      const html = legacy.call<string>('nextIntentPromptSelect', session);
      const template = document.createElement('template');
      template.innerHTML = html;
      const menu = promptMenu(draft);
      const theirsMenu = {
        visible: html !== '',
        options: [...template.content.querySelectorAll('option')]
          .filter((option) => option.value !== '')
          .map((option) => ({
            value: option.value,
            label: option.textContent ?? '',
            selected: option.hasAttribute('selected'),
          })),
      };
      checks.push(['menu', { visible: menu.visible, options: menu.options }, theirsMenu]);
      if (menu.visible && menu.options.some((option) => option.selected)) note('menu chosen');
      if (menu.visible && menu.options.length) note('menu options');
      for (const text of [
        '',
        'short',
        'x'.repeat(100),
        `${'word '.repeat(30)}tail`,
        'a'.repeat(61),
      ]) {
        checks.push(['clip', promptClip(text, 60), legacy.call('nextIntentPromptClip', text, 60)]);
      }
      const source = workSource(input.contexts, '/repo', session);
      for (const line of annotationLines(annotation)) {
        const theirs = legacy.call(
          'nextCockpitLineSource',
          line,
          session,
          legacy.call(
            'nextCockpitWorkSource',
            { label: 'x', sessions: [{ project_key: '/repo' }] },
            session,
          ),
        );
        /* Departure (owner, 2026-10-21): the page names the message's time where the retired page named an entry
           number the reader may never have been shown. Where the recording numbers the entry, the page's words
           must be the time form and nothing else is compared. */
        const ours = lineSource(line, source);
        const numbered = typeof theirs === 'string' && /^added from #\d+$/.test(theirs);
        if (numbered) {
          if (!/^added from your (\d{4}-\d{2}-\d{2} )?\d{2}:\d{2} message$/.test(ours))
            failures.push(`seed ${String(seed)} line source: ${ours}`);
        } else checks.push(['line source', ours, theirs]);
      }
      if (mineDraft) note(`draft:${mineDraft.source}`);
      if (had) note('had chosen');
      for (const [name, left, right] of checks) {
        const found = firstDifference(canonical(left), canonical(right));
        if (found) {
          failures.push(`seed ${String(seed)} ${name}: ${found}`);
          break;
        }
      }
    }
    expect(failures).toEqual([]);
    for (const name of [
      'stale',
      'draft:first-prompt',
      'draft:latest-prompt',
      'draft:chosen-prompt',
      'had chosen',
      'direction refused',
      'menu chosen',
      'menu options',
    ])
      expect(seen[name], name).toBeGreaterThan(0);
  });

  it('keeps the heldKey spelling the legacy keys use', () => {
    const session = { harness: 'claude', sid: 'a:b' };
    legacy.setData({ annotate: true });
    expect(heldKey(session, 'goal')).toBe(legacy.call('nextCockpitHeldKey', session, 'goal'));
    expect(heldKey({}, 'lines')).toBe(legacy.call('nextCockpitHeldKey', {}, 'lines'));
  });

  it('shows loading only for this session and leaves the held menu untouched', () => {
    const held = createHeld({ clock: createFakeClock(), announcer: createAnnouncer() });
    const session = { harness: 'claude', sid: 's1', first_prompt: 'Ship', first_prompt_at: 100 };
    const input: DraftInput = {
      held,
      session,
      annotation: annotationOf(session),
      payload: { annotate: true },
      contexts: new Map(),
    };
    const menu = { pending: true, open: true, choices: [] };
    held.prompts.set('claude:other', menu);
    expect(promptMenu(input).pending).toBe(false);
    held.prompts.set('claude:s1', menu);
    const version = held.getVersion();
    expect(promptMenu(input).pending).toBe(true);
    expect(held.prompts.get('claude:s1')).toBe(menu);
    expect(held.getVersion()).toBe(version);
    held.prompts.set('claude:s1', { ...menu, pending: false });
    expect(promptMenu(input).pending).toBe(false);
  });
});
