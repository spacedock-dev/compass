// @vitest-environment node
import { readFileSync, writeFileSync } from 'node:fs';
import { expect, it, vi } from 'vitest';
import { parseFocusedSummary, stampModel } from '../api/summary';
import * as observed from '../observed';
import { policyReason } from './route';
import * as sentences from './sentences';
import {
  REPLY_CUT,
  summaryStamp,
  unlinkedSentence,
  reasonSentence,
  FRESHNESS_UNKNOWN,
  GAP_LINES,
  SUMMARY_RELEVANCE,
  WITHHELD_LINES,
  WITHHELD_TITLES,
  summaryNotes,
  outOfDateLine,
  bulletWords,
  ledeWords,
} from '../sessions/summary';
import {
  BASELINE_OPEN,
  CLAUSE_UNRETAINED,
  LIVE_LEVEL_NAMES,
  PRESS_EVENTS,
  PRESS_LINES,
  UNVERIFIABLE,
} from './sentences';
import type { DriftCase } from './terminalParity.corpus.test.helper';
import { pageView } from './terminalParity.view.test.helper';

// Inputs are the existing real-server recording; wording is read from the page's own owners.
// Regenerate approved text with COMPASS_WRITE_WORDING_PARITY=1; Python consumes the same file.
const path = new URL('../../test/fixtures/terminal-wording.json', import.meta.url);
const recorded = (name: string) =>
  JSON.parse(
    readFileSync(
      new URL(`../../test/fixtures/client-contract/${name}.json`, import.meta.url),
      'utf8',
    ),
  ).response.body;

// The sample summary was recorded from the session described in sample-session/README.md.
// Cases change only coverage/freshness metadata, keeping its real blocks and words. The page
// parser and derivations write every expected sentence; no expected wording is authored here.
function summaryCases() {
  const sample = JSON.parse(
    readFileSync(new URL('../sample/session.fixture.json', import.meta.url), 'utf8'),
  );
  const base = sample.context.sources.summary;
  const sources = [
    'source_bytes',
    'source_time',
    'source_memory',
    'source_stalled',
    'source_changed',
    'oversized_line',
    'unreadable_record',
    'unreadable_subagent',
  ];
  const coverage = structuredClone(base);
  coverage.coverage.start_offset = 1;
  coverage.coverage.agent_replies = 'not_read';
  coverage.coverage.unread = sources.map((reason) => ({ reason }));
  coverage.blocks[0].span = {
    text_version: 1,
    first_offset: 1,
    first_total: 2,
    last_offset: 1,
    last_total: 2,
  };
  coverage.blocks[1].gap = true;
  coverage.blocks[1].reason = 'stopped';
  const fragmented = structuredClone(coverage);
  fragmented.blocks = [fragmented.blocks[0]];
  const notes = [base, coverage, fragmented].map((input) => {
    const summary = parseFocusedSummary({ sources: { summary: input } })?.summary;
    if (!summary) throw new Error('recorded summary could not be read');
    return {
      input: {
        coverage: input.coverage,
        blocks: input.blocks.map((block: { span?: unknown; gap?: unknown; reason?: unknown }) => ({
          span: block.span,
          gap: block.gap,
          reason: block.reason,
        })),
      },
      expected: summaryNotes(summary, ''),
    };
  });
  const freshness = [
    { kind: 'unchanged', action: 'update', new_entries: 0, affected_blocks: [] },
    { kind: 'appended', action: 'update', new_entries: 2, affected_blocks: [] },
    { kind: 'appended', action: 'update', new_entries: 1, affected_blocks: [] },
    { kind: 'appended', action: 'update', new_entries: 0, affected_blocks: [] },
  ].map((report) => {
    const input = { ...base, out_of_date: report };
    const summary = parseFocusedSummary({ sources: { summary: input } })?.summary;
    if (!summary) throw new Error('recorded summary could not be read');
    return {
      input: { made_at: input.made_at, out_of_date: input.out_of_date },
      expected: outOfDateLine(summary, { grant: null, harness: 'claude', largest: null })?.sentence,
    };
  });
  const bullets = base.blocks
    .flatMap((block: { phases: { bullets: { kind: string; text: unknown }[] }[] }) =>
      block.phases.flatMap((phase) => phase.bullets),
    )
    .filter((bullet: { text: unknown }) => typeof bullet.text === 'string')
    .map((input: { kind: string; text: string }) => ({
      input,
      expected: bulletWords(input.kind, input.text),
    }));
  const stamps = ['complete', 'running', 'stopping'].map((state) => {
    const input = { ...base, job: { ...base.job, state } };
    const summary = parseFocusedSummary({ sources: { summary: input } })?.summary;
    if (!summary) throw new Error('recorded summary could not be read');
    return {
      input: { model_stamp: input.model_stamp, made_at: input.made_at, job: input.job },
      expected: summaryStamp(summary, state !== 'complete', stampModel(input.model_stamp)),
    };
  });
  return {
    stamps,
    replyCut: REPLY_CUT,
    unlinked: [1, 3].map((count) => ({ count, expected: unlinkedSentence(count) })),
    ledeReasons: Object.fromEntries(
      ['stopped', 'bytes', 'ceiling', 'refused'].map((reason) => [
        reason,
        reasonSentence(reason, { grant: null, harness: 'claude', largest: null }),
      ]),
    ),
    notes,
    freshness,
    bullets,
    lede: { input: base.lede.text, expected: ledeWords(base.lede.text) },
  };
}

function localPageReasons() {
  const actions = readFileSync(new URL('./actions.ts', import.meta.url), 'utf8');
  const route = readFileSync(new URL('./route.ts', import.meta.url), 'utf8');
  const adoption = actions
    .split("if (answer?.['adoption_refused'])")[1]
    ?.match(/note\.message\s*=\s*'([^']+)'/);
  const beforeFinally =
    actions.split("if (answer?.['adoption_refused'])")[1]?.split('} catch')[0] ?? '';
  const messages = [...beforeFinally.matchAll(/note\.message\s*=\s*'([^']+)'/g)];
  const prompt = route
    .split('if (candidate && candidate.at === null)')[1]
    ?.match(/return '([^']+)'/);
  if (!adoption || !prompt || !messages.length)
    throw new Error('page reply wording moved; rebind its owner');
  return {
    ADOPTION_REFUSED: adoption[1],
    NOTHING_PRODUCED: messages.at(-1)?.[1],
    PROMPT_TIME_UNPUBLISHED: prompt[1],
  };
}

it('a person reads the page wording and derived reading in their terminal', () => {
  const clock = vi.spyOn(observed, 'clock').mockReturnValue('03:04');
  try {
    const payload = recorded('data-focused-drift');
    const context = recorded('context-focused-drift');
    const session = payload.sessions[0];
    const actual = {
      provenance: 'scripts/regen_client_fixtures.py: drift_view_scenario',
      view: pageView({ session, payload, context } as DriftCase),
      drift: {
        press: PRESS_LINES,
        pressEvents: PRESS_EVENTS,
        levels: LIVE_LEVEL_NAMES,
        why: { 'baseline-open': BASELINE_OPEN },
        clause: CLAUSE_UNRETAINED,
        unverifiable: UNVERIFIABLE,
        reasons: {
          ...localPageReasons(),
          MODEL_UNREAD: sentences.MODEL_UNREAD,
          MODEL_OFF: sentences.MODEL_OFF,
          ROUTE_UNREAD: sentences.ROUTE_UNREAD,
          READINGS_OFF: sentences.READINGS_OFF,
          STORE_BUSY: sentences.STORE_BUSY_PRESS,
          STORE_UNUSABLE: sentences.STORE_UNREADABLE_PRESS,
          POLICY_UNREADABLE: policyReason({ reason: 'store-unavailable' }),
        },
      },
      summary: {
        withheld: WITHHELD_LINES,
        gaps: GAP_LINES,
        titles: WITHHELD_TITLES,
        unknown: FRESHNESS_UNKNOWN,
        relevance: SUMMARY_RELEVANCE,
        ...summaryCases(),
      },
    };
    if (process.env['COMPASS_WRITE_WORDING_PARITY'] === '1') {
      writeFileSync(path, `${JSON.stringify(actual, null, 2)}\n`);
    }
    expect(actual).toEqual(JSON.parse(readFileSync(path, 'utf8')));
  } finally {
    clock.mockRestore();
  }
});
