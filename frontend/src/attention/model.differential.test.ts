import { restoredMemberKeys, unchangedAttention } from '../../test/location_departure';
import type { AttentionModel } from './model';
import { describe, expect, it } from 'vitest';
import { genPayload, mulberry32, pick } from '../observed/generate.test.helper';
import { canonical, firstDifference } from '../observed/legacy.test.helper';
import { loadLegacyAttention } from './legacy.test.helper';
import { attentionAnnouncement, attentionModel } from './model';
import { checkpointRows, subjectNow, subjectOutcome, subjectSource } from './text';

/* The Attention model and the sentences read through it are held to the legacy file that computes them.
   Generated payloads run through the real `nextAttentionModel` and through `attentionModel`, and the two
   answers must agree on every field a reader or a view can read, including which keys are present. The
   generator forces the cases that cost most when wrong (duplicate project labels, one sid under two
   harnesses, an ask with no owner, a loop split by a success, a quota that is high or fast, an end
   without a stop, unicode, wrong-typed fields), and a failure names the seed and the first path that
   differs. */
const legacy = loadLegacyAttention();
/* How many generated payloads run beside the legacy answers. The legacy answers are recorded goldens, so the
   number is what the committed record holds: raising it needs a re-record (see test/legacy_goldens.ts). */
const CASES = 80;
const SEEDS = CASES;

describe('nextAttentionModel and attentionModel agree over generated payloads', () => {
  it(`agrees on all ${String(SEEDS)} seeds`, () => {
    const failures: string[] = [];
    for (let seed = 1; seed <= SEEDS; seed += 1) {
      const payload = genPayload(seed);
      const old = legacy.model(payload);
      const mine = attentionModel(payload) as unknown as Record<string, unknown>;
      const restored = restoredMemberKeys(old as unknown as AttentionModel);
      const found = firstDifference(
        canonical(unchangedAttention(old as unknown as AttentionModel, restored)),
        canonical(unchangedAttention(mine as unknown as AttentionModel, restored)),
      );
      if (found) failures.push(`seed ${String(seed)}: ${found}`);
      if (failures.length >= 5) break;
    }
    expect(failures).toEqual([]);
  });

  it('agrees on the empty and non-object payloads the page can hold before a board arrives', () => {
    for (const payload of [
      null,
      undefined,
      {},
      [],
      'x',
      7,
      { sessions: [] },
      { sessions: 'x' },
      { sessions: [null] },
      { asks: [{ question: 'Q?' }] },
    ]) {
      const old = legacy.model(payload);
      const mine = attentionModel(payload) as unknown as Record<string, unknown>;
      expect(firstDifference(canonical(old), canonical(mine))).toBeNull();
    }
  });

  it('reaches every queue and every signal kind, so agreement means something', () => {
    const kinds = new Set<string>();
    const sections = { needs: 0, risk: 0, close: 0, next: 0 };
    let split = 0;
    let barren = 0;
    for (let seed = 1; seed <= SEEDS; seed += 1) {
      const model = attentionModel(genPayload(seed));
      for (const section of ['needs', 'risk', 'close', 'next'] as const) {
        sections[section] += model[section].length;
        for (const subject of model[section])
          for (const signal of subject.signals) {
            kinds.add(signal.kind);
            if (signal.kind === 'loop' && signal.detail.failures !== undefined) split += 1;
            if (signal.kind === 'loop' && signal.detail.barren) barren += 1;
          }
      }
    }
    for (const kind of [
      'ask',
      'input',
      'attribution',
      'loop',
      'quota',
      'long-turn',
      'collision',
      'task',
    ])
      expect(kinds, kind).toContain(kind);
    expect([...kinds].some((kind) => kind.startsWith('end-'))).toBe(true);
    expect([...kinds].some((kind) => kind.startsWith('stop-'))).toBe(true);
    expect(Object.values(sections).every((count) => count > 0)).toBe(true);
    expect(split).toBeGreaterThan(0);
    expect(barren).toBeGreaterThan(0);
  });

  it('agrees on quota windows built around the level and pace boundaries, and reaches a pace signal', () => {
    const rnd = mulberry32(7);
    const windows = [18000, 604800, 0, -5, null, 'x'] as const;
    const pcts = [0, 9, 10, 11, 34, 69, 70, 89, 90, 100, 5.5, 'x', null] as const;
    const at = 1000;
    const failures: string[] = [];
    let pace = 0;
    let level = 0;
    for (let seed = 1; seed <= Math.min(SEEDS, 60); seed += 1) {
      const window = () => {
        const windowSec = pick(rnd, windows);
        const span = typeof windowSec === 'number' && windowSec > 0 ? windowSec : 18000;
        return {
          pct: pick(rnd, pcts),
          windowSec,
          // The reset sits where the elapsed share is 0, just under or over a tenth, a third, all of it, and past it.
          resetAt: pick(rnd, [
            at + span,
            at + span * 0.9,
            at + span * 0.9 + 1,
            at + span * 0.66,
            at + 10,
            at,
            at - 5,
            null,
            'x',
          ]),
        };
      };
      const payload = {
        generated: pick(rnd, [at, at, null, 'x']),
        sessions: [],
        usage: [
          {
            harness: 'claude',
            state: 'ok',
            fiveH: window(),
            week: window(),
            month: window(),
            models: [{ label: 'Opus', ...window() }, { ...window() }],
          },
          { harness: 'claude', state: pick(rnd, ['ok', 'error']), fiveH: window() },
        ],
      };
      const old = legacy.model(payload);
      const mine = attentionModel(payload) as unknown as Record<string, unknown>;
      const found = firstDifference(canonical(old), canonical(mine));
      if (found) failures.push(`seed ${String(seed)}: ${found}`);
      for (const subject of attentionModel(payload).risk)
        for (const signal of subject.signals) {
          if (signal.detail.reason === 'pace') pace += 1;
          if (signal.detail.reason === 'level') level += 1;
        }
      if (failures.length >= 5) break;
    }
    expect(failures).toEqual([]);
    expect(pace).toBeGreaterThan(0);
    expect(level).toBeGreaterThan(0);
  });
});

describe('the close queue is ordered by what is at stake, then by when', () => {
  it('agrees with the legacy order for every ending and stop, whichever way the board lists them', () => {
    const kinds: [string, Record<string, unknown>][] = [
      ['end-dirty', { ended_at: 900, dirty: true, changed: 2, finished_at: 880 }],
      ['end-clean', { ended_at: 910, dirty: false, finished_at: 890 }],
      ['end-unknown', { ended_at: 920, finished_at: 870 }],
      ['stop-dirty', { state: 'idle', finished_at: 860, dirty: true }],
      ['stop-clean', { state: 'idle', finished_at: 850, dirty: false }],
      ['stop-unknown', { state: 'idle', finished_at: 840 }],
    ];
    const rows = kinds.map(([sid, fields]) => ({
      harness: 'claude',
      sid,
      project: `p/${sid}`,
      state: 'idle',
      ...fields,
    }));
    for (const order of [
      rows,
      [...rows].reverse(),
      [rows[3], rows[0], rows[5], rows[1], rows[4], rows[2]],
    ]) {
      const payload = { generated: 1000, sessions: order };
      const old = legacy.model(payload);
      const mine = attentionModel(payload);
      expect(firstDifference(canonical(old), canonical(mine))).toBeNull();
      expect(mine.close.map((subject) => subject.primaryKind)).toEqual([
        'end-dirty',
        'stop-dirty',
        'end-unknown',
        'stop-unknown',
        'end-clean',
        'stop-clean',
      ]);
    }
  });
});

describe('the sentences a subject is read through agree with the legacy builders', () => {
  it('reads outcome, now, next and source the same way for every subject', () => {
    const failures: string[] = [];
    for (let seed = 1; seed <= Math.min(SEEDS, 50); seed += 1) {
      const payload = genPayload(seed);
      legacy.setData(payload);
      const oldModel = legacy.call<Record<string, unknown>>('nextAttentionModel', payload);
      const model = attentionModel(payload);
      for (const section of ['needs', 'risk', 'close', 'next'] as const) {
        const oldSubjects = oldModel[section] as Record<string, unknown>[];
        oldSubjects.forEach((old, index) => {
          const subject = model[section].find((row) => row.key === old['key']);
          const recorded = [
            legacy.call('nextAttentionSubjectNow', old, oldModel),
            legacy.call('nextAttentionOutcome', old, oldModel),
            legacy.call('nextAttentionCheckpointRows', old, oldModel),
            legacy.call('nextAttentionSubjectSource', old, oldModel),
          ];
          if (old['kind'] === 'collision') return;
          if (!subject) throw new Error(`Unchanged subject missing: ${String(old['key'])}`);
          const current = [
            subjectNow(subject, model),
            subjectOutcome(subject, model),
            checkpointRows(subject, model),
            subjectSource(subject, model),
          ];
          for (const [at, name] of ['now', 'outcome', 'next', 'source'].entries()) {
            const found = firstDifference(canonical(recorded[at]), canonical(current[at]));
            if (found)
              failures.push(`seed ${String(seed)} ${section}[${String(index)}] ${name}: ${found}`);
          }
        });
      }
      if (failures.length >= 5) break;
    }
    expect(failures).toEqual([]);
  });

  it('announces the counts in the current queues, and nothing for an unchanged count', () => {
    const failures: string[] = [];
    for (let seed = 1; seed <= Math.min(SEEDS, 50); seed += 1) {
      const before = genPayload(seed);
      const after = genPayload(seed + 1000);
      // Consume the historical sentence; its queue counts included the old folding.
      legacy.announcement(before, after);
      const counted = attentionModel(after);
      const words = (['needs', 'risk', 'close', 'next'] as const).flatMap((kind, index) =>
        counted[kind].length
          ? [
              `${String(counted[kind].length)} ${['need you', 'at risk', 'close the loop', 'coming next'][index]}`,
            ]
          : [],
      );
      const changed = (['needs', 'risk', 'close', 'next'] as const).some(
        (kind) => attentionModel(before)[kind].length !== counted[kind].length,
      );
      const old = changed
        ? `Attention updated: ${(words.length ? words : ['0 need you', '0 at risk']).join(', ')}`
        : '';
      const mine = attentionAnnouncement(attentionModel(before), attentionModel(after));
      if (old !== mine)
        failures.push(`seed ${String(seed)}: ${JSON.stringify(old)} != ${JSON.stringify(mine)}`);
      expect(attentionAnnouncement(attentionModel(after), attentionModel(after))).toBe('');
    }
    expect(failures).toEqual([]);
    expect(attentionAnnouncement(null, attentionModel(genPayload(1)))).toBe('');
  });
});
