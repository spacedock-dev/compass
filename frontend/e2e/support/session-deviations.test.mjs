import assert from 'node:assert/strict';
import { test } from 'node:test';
import { normaliseSessionRecord } from './session-deviations.mjs';
import { recordedLocationNotes, unchangedAttentionLocations } from './location-deviations.mjs';

test('a recorded location note changes without rewriting a title that quotes it', () => {
  const warning = '2 sessions share this display label; shared location is not established';
  const record = {
    groups: [
      {
        rows: [{ harness: 'claude', sid: 'one', text: `Title: ${warning}${warning}PROJECTaudits` }],
      },
    ],
  };
  const sessions = ['one', 'two'].map((sid) => ({
    harness: 'claude',
    sid,
    project: 'audits',
    title: warning,
    project_key: 'path:one',
    project_identity_source: 'working directory path',
  }));
  assert.equal(
    recordedLocationNotes(record, { sessions }).groups[0].rows[0].text,
    `Title: ${warning}PROJECTaudits`,
  );
  assert.equal(record.groups[0].rows[0].text, `Title: ${warning}${warning}PROJECTaudits`);
  sessions[1].project_identity_source = 'collector project label';
  sessions[1].project_key = 'audits';
  assert.equal(
    recordedLocationNotes(record, { sessions }).groups[0].rows[0].text,
    `Title: ${warning}Location not measured for 1 session with this display labelPROJECTaudits`,
  );
  sessions[1].project_identity_source = 'working directory path';
  sessions[1].project_key = 'path:two';
  assert.equal(
    recordedLocationNotes(record, { sessions }).groups[0].rows[0].text,
    `Title: ${warning}2 sessions share this display label across 2 measured locationsPROJECTaudits`,
  );
});

test('a project recording changes only its location note and preserves member words', () => {
  const warning = '2 sessions share this display label; shared location is not established';
  const sessions = ['one', 'two'].map((sid) => ({ harness: 'claude', sid, project: 'audits' }));
  const record = { header: `audits2 sessions${warning}`, panel: warning };
  assert.deepEqual(recordedLocationNotes(record, { sessions }, 'audits'), {
    header: 'audits2 sessionsLocation not measured for 2 sessions with this display label',
    panel: warning,
  });
  const summary = {
    brief: '2 to close',
    sections: [
      { name: 'close', items: [{ subject: 'session:one', text: 'Keep the stop' }] },
      { name: 'board-risk', items: [{ subject: 'collision:audits', text: 'Retired warning' }] },
    ],
  };
  assert.deepEqual(
    unchangedAttentionLocations(summary).sections[0].items,
    summary.sections[0].items,
  );
  assert.deepEqual(unchangedAttentionLocations(summary).sections[1].items, []);
});

test('session deviations preserve quoted titles and instructions', () => {
  const words = 'Fix ASSIGNMENT parsing';
  assert.deepEqual(
    normaliseSessionRecord(
      {
        title: words,
        saved: ['Copy session ID a'],
        metadata: { header: 'Copy link', text: words },
        groups: [{ rows: [{ text: `ASSIGNMENT · ${words}` }] }],
      },
      { instruction: words },
    ),
    {
      title: words,
      saved: ['Copy session ID a'],
      metadata: { header: 'Copy link', text: words },
      groups: [{ rows: [{ text: `Current task · ${words}` }] }],
    },
  );
});

test('a reader sees a published session age in the projected recorded header only', () => {
  const evidence = {
    generated: 1900000000,
    sessions: [
      {
        harness: 'claude',
        sid: 's1',
        project: 'alpha/app',
        started_at: 1900000000 - 23 * 3600,
        finished_at: 1900000000 - 60,
      },
    ],
  };
  const record = {
    attrs: ['s1', 'idle', 'quiet', false],
    header: 'State: idleSyntheticclaude · s1 · 0 /m · alpha/appClaude Code · idle',
    metadata: { header: 'Same words' },
  };
  const projected = normaliseSessionRecord(record, evidence);
  assert.equal(
    projected.header,
    'State: QuietSyntheticclaude · s1 · 0 /m · alpha/app · Started about 23h 0m agoClaude Code · idle',
  );
  assert.equal(projected.metadata.header, 'Same words');
  assert.equal(record.header.includes('Started about'), false);
  assert.equal(
    normaliseSessionRecord(record, {
      ...evidence,
      sessions: [{ ...evidence.sessions[0], started_at: null }],
    }).header.includes('Started about'),
    false,
  );
});

test('a project with an empty display label says its members have no measured location', () => {
  const warning = '2 sessions share this display label; shared location is not established';
  const sessions = [
    { harness: 'claude', sid: 'one', project: '' },
    { harness: 'claude', sid: 'two', project: null },
  ];
  const record = {
    groups: [{ rows: [{ project: '', text: `Exact location not published${warning}` }] }],
  };
  assert.equal(
    recordedLocationNotes(record, { sessions }).groups[0].rows[0].text,
    'Exact location not publishedLocation not measured for 2 sessions with this display label',
  );
  assert.equal(record.groups[0].rows[0].text, `Exact location not published${warning}`);
});

test('only a recorded turn end projects a retired Idle header to Quiet', () => {
  const record = {
    attrs: ['one', 'idle', 'ok', false],
    header: 'State: idleFix the buildclaude · one',
  };
  const one = { sid: 'one', harness: 'claude', state: 'idle' };
  for (const source of [one, { ...one, acquisition: 'scan-only' }]) {
    const projected = normaliseSessionRecord(record, { sessions: [source] });
    assert.equal(projected.header, 'Fix the buildclaude · one');
  }
  const observed = normaliseSessionRecord(record, {
    sessions: [{ ...one, finished_at: 1900000000 }],
  });
  assert.equal(observed.header, 'State: QuietFix the buildclaude · one');
});
