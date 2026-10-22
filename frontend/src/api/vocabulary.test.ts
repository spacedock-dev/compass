// @vitest-environment node
/* The words, keys and rules the Python producers and the React page each spell, held together. The fixture
   (`frontend/test/fixtures/vocabulary.json`) is read from the Python modules by
   `scripts/regen_client_fixtures.py`, whose `--check` fails when a Python constant moves without it. Every
   test here imports the React constant where it lives and compares it with the fixture, so a change on
   either side fails until the other follows. Nothing is copied into this file. These replaced the Python
   tests that compared the retired page's source text with the same constants. */
import { readdirSync, readFileSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';
import { ASSESSMENT_KEYS } from '../drift/shape';
import {
  BLOCKER_LINES,
  CORRECTION_CAP,
  CRITERION_KEYS,
  REASON_LINES,
  RESULTS,
  SCOPE_TEXT_IDLE,
  SILENT_REASONS,
  STORED_WHY,
} from '../drift/sentences';
import { CUE_TTL_MS } from '../controls/keyedState';
import { CHECK_NOT_RECORDED_REASONS, toolReportLine } from '../drift/workList';
import { DELETE_LAPSE_SECONDS } from '../sessions/summary';
import {
  ANNOTATION_FIELDS,
  HELD_UNSAFE,
  OUTCOME_LINES_MAX,
  revisionLine,
} from '../intent/annotation';
import { WORK_BY_HARNESS, type WorkEntry } from '../intent/work';
import { askBanner, notifyEdge, sessionBanner } from '../notify/edges';
import { READING_TURN_STOP_HARNESSES } from '../observed';
import { askingTitle, departureRow } from '../sessions/detail';
import { revisionSuperseded } from '../sessions/rows';
import {
  PROMPT_CHOSEN,
  PROMPT_SOURCES,
  READING_ASSESSMENT_KEYS,
  SESSION_GOAL,
  readingNamesConstraint,
} from '../sessions/intent';

interface Vocabulary {
  readonly assessmentKeys: string[];
  readonly criterionKeys: string[];
  readonly whyTokens: string[];
  readonly workEvidenceByHarness: Record<string, string[]>;
  readonly checkResultWords: Record<string, string>;
  readonly checkNotRecorded: string;
  readonly checkNotRecordedReasons: Record<string, string>;
  readonly checkEarlierFailed: string;
  readonly checkBeforeLastChange: string;
  readonly results: string[];
  readonly promptSources: string[];
  readonly promptChosen: string;
  readonly sessionGoal: string;
  readonly maxOutcomeLines: number;
  readonly cueWindowSeconds: number;
  readonly turnStopHarnesses: string[];
  readonly scopeTextMidFlightIdle: string;
  readonly correctionCapChars: number;
  readonly levelReasons: string[];
  readonly annotationFields: string[];
  readonly unsafeChars: { readonly codePoints: [number, number][] };
  readonly titles: {
    readonly waiting: Record<string, string>;
    readonly asking: Record<string, string>;
  };
  readonly waitBodies: { project: string; state_detail: string; body: string }[];
  readonly askDetails: { question: string; project: string; detail: string }[];
}

const vocabulary = JSON.parse(
  readFileSync(new URL('../../test/fixtures/vocabulary.json', import.meta.url), 'utf8'),
) as Vocabulary;

const sorted = (values: Iterable<string>): string[] => [...values].sort();

describe('the cue window', () => {
  it('is the lifetime of a held cue, and the lapse Delete summary and the armed discard each name', () => {
    expect(CUE_TTL_MS).toBe(vocabulary.cueWindowSeconds * 1000);
    expect(DELETE_LAPSE_SECONDS).toBe(vocabulary.cueWindowSeconds);
  });
});

describe('the reading vocabulary', () => {
  it('names the same assessment keys as the producer', () => {
    expect(sorted(ASSESSMENT_KEYS)).toEqual(sorted(vocabulary.assessmentKeys));
    expect(sorted(READING_ASSESSMENT_KEYS)).toEqual(sorted(vocabulary.assessmentKeys));
  });

  it('names the same criterion keys as the producer', () => {
    expect(sorted(CRITERION_KEYS)).toEqual(sorted(vocabulary.criterionKeys));
  });

  it('has a sentence for every reason a stored row may give, and none the producer lacks', () => {
    expect(sorted(Object.keys(STORED_WHY))).toEqual(sorted(vocabulary.whyTokens));
  });

  it('agrees on which entries demonstrate work, for every harness', () => {
    expect(
      Object.fromEntries(
        Object.entries(WORK_BY_HARNESS).map(([name, types]) => [name, sorted(types)]),
      ),
    ).toEqual(vocabulary.workEvidenceByHarness);
  });

  it('spells the three results a reader can see, and the others, as the producer does', () => {
    expect(sorted(RESULTS)).toEqual(sorted(vocabulary.results));
  });

  it('gives every reason the producer publishes exactly one home, and invents none', () => {
    const homes = [...Object.keys(REASON_LINES), ...Object.keys(BLOCKER_LINES), ...SILENT_REASONS];
    expect(new Set(homes).size).toBe(homes.length);
    expect(sorted(homes)).toEqual(sorted(vocabulary.levelReasons));
  });
});

describe('the words beside a check', () => {
  const entry = (result: string, resultSource: string, flags: Partial<WorkEntry> = {}): WorkEntry =>
    ({
      subject: 'check',
      result,
      resultSource,
      earlierFailed: false,
      beforeLastChange: false,
      ...flags,
    }) as WorkEntry;

  it('reads every result word the producer carries, so the model and the reader see one strength', () => {
    for (const [key, words] of Object.entries(vocabulary.checkResultWords)) {
      const [result, source] = key.split(' ') as [string, string];
      expect(toolReportLine(entry(result, source))).toBe(`Agent · check · ${words}`);
    }
  });

  it('says what the producer says for a result nobody recorded and for the two flags', () => {
    expect(toolReportLine(entry('', ''))).toBe(`Agent · check · ${vocabulary.checkNotRecorded}`);
    expect(toolReportLine(entry('', '', { earlierFailed: true, beforeLastChange: true }))).toBe(
      `Agent · check · ${vocabulary.checkNotRecorded} · ${vocabulary.checkEarlierFailed} · ${vocabulary.checkBeforeLastChange}`,
    );
  });

  it('names the rule that withheld a result in the words the producer publishes, and no other', () => {
    expect(CHECK_NOT_RECORDED_REASONS).toEqual(vocabulary.checkNotRecordedReasons);
    for (const [token, words] of Object.entries(vocabulary.checkNotRecordedReasons)) {
      expect(toolReportLine(entry('', '', { resultReason: token }))).toBe(
        `Agent · check · ${vocabulary.checkNotRecorded} · ${words}`,
      );
    }
    expect(toolReportLine(entry('', '', { resultReason: 'unknown-token' }))).toBe(
      `Agent · check · ${vocabulary.checkNotRecorded}`,
    );
  });
});

describe('the goal and the annotation', () => {
  it('spells the prompt sources as the server does', () => {
    expect(sorted(PROMPT_SOURCES)).toEqual(sorted(vocabulary.promptSources));
    expect(PROMPT_CHOSEN).toBe(vocabulary.promptChosen);
    expect(PROMPT_SOURCES).toContain(PROMPT_CHOSEN);
    expect(SESSION_GOAL).toBe(vocabulary.sessionGoal);
    expect(PROMPT_SOURCES).toContain(SESSION_GOAL);
  });

  it('reads exactly the fields the store publishes', () => {
    expect(sorted(ANNOTATION_FIELDS)).toEqual(sorted(vocabulary.annotationFields));
  });

  it('bounds the outcome lines where the store does, in both places the page spells it', () => {
    expect(OUTCOME_LINES_MAX).toBe(vocabulary.maxOutcomeLines);
    // The session row's own copy is not exported (exporting it moves the shipped bundle), so it is
    // read through the one function that applies it: the last line the store keeps, and the next.
    const last = `line_${String(vocabulary.maxOutcomeLines)}`;
    const over = `line_${String(vocabulary.maxOutcomeLines + 1)}`;
    expect([readingNamesConstraint(last), readingNamesConstraint(over)]).toEqual([true, false]);
  });

  it('strips exactly the characters the store strips', () => {
    const one = new RegExp(`^(?:${HELD_UNSAFE.source})$`);
    const runs: [number, number][] = [];
    for (let point = 0; point < 0x10000; point += 1) {
      if (!one.test(String.fromCharCode(point))) continue;
      const last = runs.at(-1);
      if (last && last[1] === point - 1) last[1] = point;
      else runs.push([point, point]);
    }
    expect(runs).toEqual(vocabulary.unsafeChars.codePoints);
  });

  it('admits the turn stop for the harnesses the server does', () => {
    expect(sorted(READING_TURN_STOP_HARNESSES)).toEqual(sorted(vocabulary.turnStopHarnesses));
  });

  it('knows an idle reading by the sentence the producer stores', () => {
    expect(SCOPE_TEXT_IDLE).toBe(vocabulary.scopeTextMidFlightIdle);
  });

  it('caps the correction where the copy route does', () => {
    expect(CORRECTION_CAP).toBe(vocabulary.correctionCapChars);
  });
});

describe('the alert the page and the server both compose', () => {
  const labelled = (label: string) => ({
    harnesses: label ? [{ key: 'claude', label }] : [],
  });

  it('titles a waiting session as the server does', () => {
    for (const [label, title] of Object.entries(vocabulary.titles.waiting)) {
      if (!label) continue;
      const session = { harness: 'claude', project: 'p', state: 'needs_input', active: true };
      const edge = notifyEdge(session, 'working');
      expect(edge).not.toBeNull();
      if (edge) expect(sessionBanner(labelled(label), session, edge).title).toBe(title);
    }
  });

  it('titles a question as the server does, with the generic subject for an unnamed harness', () => {
    for (const [label, title] of Object.entries(vocabulary.titles.asking)) {
      const ask = { harness: 'claude', question: 'Which branch?', project: '', id: 'a' };
      expect(askBanner(labelled(label), [ask]).title).toBe(title);
      const names = new Map(label ? [['claude', label]] : []);
      expect(askingTitle(names, { harness: 'claude' })).toBe(title);
    }
  });

  it('composes the waiting body and the question detail as the server does', () => {
    for (const { project, state_detail: detail, body } of vocabulary.waitBodies) {
      const session = {
        harness: 'claude',
        project,
        state: 'needs_input',
        active: true,
        state_detail: detail,
      };
      const edge = notifyEdge(session, 'working');
      if (edge) expect(sessionBanner(labelled('Claude Code'), session, edge).body).toBe(body);
    }
    for (const { question, project, detail } of vocabulary.askDetails) {
      const ask = { harness: 'claude', question, project, id: 'a' };
      expect(askBanner(labelled('Claude Code'), [ask]).body).toBe(detail);
    }
  });
});

/* "Revision 2 is current" was the only sentence in the page that named a revision, and a reader cannot act
   on it: the number appears nowhere else. A stale reading or raise names the moments instead (docs/design-reading-a-session.md,
   "Amended 2026-10-21 (owner): editing the goal keeps the reading's start"). */
describe('the sentences about words that moved on name times, not revision numbers', () => {
  const NUMBERED = /(?:revision|version)\s*(?:\d|\$\{)/i;

  it('says when a reading or a raise was made and when the intent changed', () => {
    for (const subject of ['This reading', 'This raise']) {
      const line = revisionSuperseded(subject, 2, 3, 1_700_000_000, 1_700_000_500);
      expect(line).toMatch(
        new RegExp(
          `^${subject} was made at .+ against an earlier version of your intent\\. You changed it at .+, so it does not describe what you are asking for now\\.$`,
        ),
      );
      expect(line).not.toMatch(NUMBERED);
    }
  });

  it('leaves a moment out rather than inventing one, and says nothing when nothing moved', () => {
    expect(revisionSuperseded('This reading', 2, 3)).toBe(
      'This reading was made against an earlier version of your intent. You changed it, so it does not describe what you are asking for now.',
    );
    expect(revisionSuperseded('This reading', 3, 3, 1, 2)).toBe('');
    expect(revisionSuperseded('This reading', null, 3, 1, 2)).toBe('');
  });

  it('words a raise’s baseline and its stale line without a number', () => {
    for (const revision of [2, 0]) {
      const row = departureRow({ at: 960, revision, constraint: 'TYPED GOAL' }, 3, 1000);
      expect(`${row.base} ${row.stale}`).not.toMatch(NUMBERED);
    }
    expect(departureRow({ at: 960, revision: 2 }, 3, 1000).base).toBe(
      'read against the intent as it stood then · the evidence window is not on record',
    );
    expect(departureRow({ at: 960, revision: 0 }, 3, 1000).base).toBe(
      'the intent it read is not on record · the evidence window is not on record',
    );
  });

  it('words the saved line under the goal as a time, and the store’s bound as dropped saves', () => {
    const annotation = (extra: Record<string, unknown>) => ({
      revision: 4,
      revision_count: 4,
      at: 700,
      goal_source: '',
      ...extra,
    });
    expect(revisionLine(annotation({}), 1000)).toBe('typed 5m ago');
    expect(revisionLine(annotation({ goal_source: 'first-prompt' }), 1000)).toBe('saved 5m ago');
    expect(revisionLine(annotation({ revision: 20, revision_count: 16 }), 1000)).toBe(
      'typed 5m ago · older saves dropped',
    );
    expect(revisionLine(annotation({ at: null }), 1000)).toBe('typed, when not recorded');
    expect(revisionLine(annotation({ revision_count: 0 }), 1000)).toBe('');
  });

  it('prints no revision number from any shipped source', () => {
    const files: string[] = [];
    const walk = (dir: string): void => {
      for (const entry of readdirSync(dir, { withFileTypes: true })) {
        const path = join(dir, entry.name);
        if (entry.isDirectory()) walk(path);
        else if (
          /\.tsx?$/.test(entry.name) &&
          !/\.(test|testing|differential)\.|\.stories\./.test(entry.name)
        )
          files.push(path);
      }
    };
    walk(new URL('..', import.meta.url).pathname);
    expect(files.length).toBeGreaterThan(50);
    const found = files.flatMap((path) => {
      // Comments say why; only what is drawn is held to the vocabulary.
      const code = readFileSync(path, 'utf8')
        .replace(/\/\*[\s\S]*?\*\//g, '')
        .replace(/^\s*\/\/.*$/gm, '');
      return code
        .split('\n')
        .filter((line) => NUMBERED.test(line))
        .map((line) => `${path}: ${line.trim()}`);
    });
    expect(found).toEqual([]);
  });
});
