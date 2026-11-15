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
      { harness: 'claude', sid: 's1', project: 'alpha/app', started_at: 1900000000 - 23 * 3600 },
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
    'State: idleSyntheticclaude · s1 · 0 /m · alpha/app · Started about 23h 0m agoClaude Code · idle',
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
