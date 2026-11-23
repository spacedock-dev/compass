import assert from 'node:assert/strict';
import { goldenFor, jsonSafe, normalise } from './golden.mjs';
import { recordedLocationNotes } from './location-deviations.mjs';

/* DEC-27's retracted controls and relocated explanation change only the recorded
   side. React observations retain every control and word, so regressions fail. */
export function sessionDeviations(proof, payload = () => ({})) {
  const golden = goldenFor(proof);
  const seen = new Map();
  return {
    ...golden,
    recorded: (key) => normaliseSessionRecord(golden.recorded(key), payload()),
    observe(key) {
      const value = normaliseSessionRecord(golden.observe(key), payload());
      seen.set(key, value);
      return value;
    },
    verify(key, value) {
      assert.ok(seen.has(key));
      assert.deepEqual(jsonSafe(normalise(value)), seen.get(key), `${proof}: ${key}`);
    },
  };
}

export function normaliseSessionRecord(record, evidence = {}) {
  record = recordedLocationNotes(record, evidence);
  const words = new Set();
  const collect = (value) => {
    if (
      typeof value === 'string' &&
      /ASSIGNMENT|Copy ID|Copy link|Copy command|COMMAND SURFACE|How rows are split|Goal sources|No resume command|What analysis does|[●○△◦✓]/.test(
        value,
      )
    )
      words.add(value.replace(/\s+/g, ' ').trim());
    else if (Array.isArray(value)) value.forEach(collect);
    else if (value && typeof value === 'object') Object.values(value).forEach(collect);
  };
  collect(evidence);
  const escaped = [...words]
    .sort((a, b) => b.length - a.length)
    .map((word) => word.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'));
  const pattern = escaped.length ? new RegExp(escaped.join('|'), 'g') : null;
  const preserve = (value, change) => {
    const held = [];
    const masked = pattern
      ? value.replace(pattern, (word) => `\uE000${held.push(word) - 1}\uE001`)
      : value;
    return change(masked).replace(/\uE000(\d+)\uE001/g, (_match, index) => held[Number(index)]);
  };
  const retract = (value, key = '', path = []) => {
    if (typeof value === 'string') {
      const sessionHeader =
        key === 'header' &&
        path.length === 1 &&
        (Array.isArray(record?.groups) || Array.isArray(record?.attrs));
      const driftCard = key === 'text' && path.length === 1 && Array.isArray(record?.resultStates);
      const sessionRow = key === 'text' && path.includes('rows');
      if (!sessionHeader && !driftCard && !sessionRow && !path.includes('parts')) return value;
      if (
        path.includes('.next-cockpit-departures-kept') &&
        value ===
          'Intent logWhat it keepsThe Intent log keeps what you saved and what was raised against it after the session leaves the board.'
      ) {
        return 'Goal historyWhat it keepsGoal history keeps what you saved and what was raised against it after the session leaves the board.';
      }
      return preserve(value, (value) => {
        // 2026-11-22, docs/design-frontend-migration.md#held-to-recorded-answers
        if (sessionRow) value = maskRecordedSessionRowMarks(value);
        if (sessionHeader && Array.isArray(record?.attrs)) {
          const rows = (evidence.sessions ?? []).filter((row) => row.sid === record.attrs[0]);
          const owner =
            rows.length === 1
              ? rows[0]
              : rows.find((row) => value.includes(`${row.harness} · ${row.sid}`));
          value = projectRecordedStateWord(value, owner);
        }
        if (path.includes('[data-next-session-subagents]'))
          value = value
            .replace(
              /^\d+ (?:RUNNING )?SUBAGENTS?(?: · NONE RUNNING)?(?: · \d+ WORKERS? RUNNING BENEATH)?/,
              '',
            )
            .replace(/[●○✓]/g, '');
        if (path.includes('[data-next-session-section="tasks"]'))
          value = value.replace(/[●○✓]/g, '');
        if (key === 'text' && path.includes('rows'))
          value = value.replace(/ASSIGNMENT · /, 'Current task · ');
        if (path.includes('parts') && path.includes('.next-session-evidence'))
          value = value.replace(/^ASSIGNMENT/, 'Current task');
        value = value.replace(
          "Last turn isn't recorded as finished. Run another turn to open Analyze.",
          'Analyze opens while this session runs.',
        );
        // The retired page printed "N of 10 left today" under every reading; the React page prints the budget only
        // at the cap (`readingCap` in frontend/src/drift/route.ts), and ReadingResult.test.tsx holds that under the
        // cap it is not mentioned anywhere. Only the recorded side loses it, and only under the cap.
        if (driftCard) value = value.replace(/\d+ of \d+ left today/g, '');
        if (driftCard)
          value = value
            .replace(
              'You gave a later direction at #1: "Keep the flag off by default."',
              '1 later direction since saving your intent.',
            )
            // The correction box is "Correction to paste" (2026-10-21, docs/design-frontend-migration.md#held-to-recorded-answers).
            .replaceAll('Correction to copy', 'Correction to paste');
        if (sessionHeader && !(record?.attrs?.[3] || record?.ask || record?.answers?.length))
          value = value.replace(
            /(?:No resume command · )?(?:No terminal to raise|Terminal raise off)Why.*$/,
            '',
          );
        if (key === 'header' || key === 'text')
          return value
            .replace(/Copy ID|Copy link|Copy command/g, '')
            .replaceAll('COMMAND SURFACE', '')
            .replaceAll('How rows are split', '')
            .replaceAll('Goal sources', '')
            .replace(
              /No resume commandWhy(?:This session published no usable id this run|[^.]* publishes no re-entry command), so (?:there is no re-entry command to copy|there is none to copy)\./g,
              '',
            )
            .replace(/No resume command · | · No resume command|No resume command/g, '')
            .replace(
              /(?:This session published no usable id this run|(?<=Why)[^.]* publishes no re-entry command), so (?:there is no re-entry command to copy|there is none to copy)\./g,
              '',
            )
            .replace(
              /What analysis does(?:When you analyze drift, Compass lists where this session departed from your saved goal\. |Choose a goal or use your prompt, then analyze drift: Compass lists where this session departed from it\. )It never writes into the session, so steering stays yours\./g,
              '',
            )
            .trimEnd();
        return value;
      });
    }
    if (Array.isArray(value))
      return value
        .filter(
          (item) =>
            !(
              ['headerButtons', 'buttons', 'copyLabels'].includes(key) &&
              typeof item === 'string' &&
              /^Copy (session ID |a link to this session|re-entry command )/.test(item)
            ),
        )
        .filter(
          (item) =>
            !(
              ['buttons', 'controls'].includes(key) &&
              Array.isArray(item) &&
              ['Copy ID', 'Copy link', 'Copy command'].includes(item[0])
            ),
        )
        .map((item) =>
          retract(item, key, [
            ...path,
            ...(Array.isArray(item) && typeof item[0] === 'string' ? [item[0]] : []),
          ]),
        );
    if (value && typeof value === 'object') {
      if (
        value === record &&
        Array.isArray(value.resultStates) &&
        value.resultStates.length &&
        !value.stale?.length &&
        typeof value.text === 'string' &&
        Array.isArray(value.buttons)
      )
        value = {
          ...value,
          text: value.text.replace('Analyze again', ''),
          buttons: value.buttons.filter(([label]) => label !== 'Analyze again'),
        };
      return Object.fromEntries(
        Object.entries(value).map(([name, item]) => [
          name,
          retract(name === 'fleet' ? item.slice(0, 2) : item, name, [...path, name]),
        ]),
      );
    }
    return value;
  };
  const result = retract(record);
  projectPublishedSessionAge(result, evidence);
  if (Array.isArray(result?.groups) && typeof result.header === 'string') {
    const available =
      evidence.annotate === true &&
      !evidence.annotate_unreadable &&
      Object.values(evidence.reading_routes || {}).some((route) => route?.provider);
    const sentence = available
      ? 'Open a session, set its goal and press Analyze drift to see how far it moved from it.'
      : 'Open a session to see what it is doing and where it stands.';
    const unchecked = 'No session has been checked for drift yet; open one to check it.';
    result.header = result.header.replace(
      'Session operations',
      `Session operations${sentence}${available && result.header.includes(unchecked) ? ' ' : ''}`,
    );
    if (!available) result.header = result.header.replace(unchecked, '');
    // Board caveats moved under the history disclosure. SessionsView.test holds their new home.
    result.header = result.header.split(
      'Blocked sessions lead, followed by recorded departures',
    )[0];
    const history = result.groups.find((group) => group.kind === 'history');
    const hours = evidence.window_hours;
    if (history?.header.startsWith('Recent historyWhat recent means')) {
      history.header =
        evidence.show_all === true
          ? 'Session history'
          : typeof hours === 'number' && Number.isFinite(hours) && hours > 0
            ? `Earlier in the last ${hours} ${hours === 1 ? 'hour' : 'hours'}`
            : 'Recently active';
    }
  }
  return result;
}

function maskRecordedSessionRowMarks(text) {
  return text
    .replace(/●/g, '')
    .replace(/[△✓◦]\s*(?=Session ended|Stop observed|Turn stop in)/g, '')
    .replace('Read by scanning: no turn end can be observed here', '');
}

function projectRecordedStateWord(text, row) {
  const stop =
    Number(row?.finished_at) > 0 ||
    (['claude', 'codex'].includes(row?.harness) && Number(row?.turn_end_at) > 0);
  return text
    .replace(/^State: working/, 'State: Working')
    .replace(/^State: needs input/, 'State: Waiting on you')
    .replace(/^State: idle/, stop ? 'State: Quiet' : '')
    .replace(/ · read by scanning: no turn end can be observed here/, '')
    .replace(/^State: ended/, 'State: Ended');
}

// The owner appended age to the identity line. Keep the recording's words, adding only the
// independently published timestamp's duration; never change a title, instruction or nested header.
function projectPublishedSessionAge(record, evidence) {
  if (!Array.isArray(record?.attrs) || typeof record.header !== 'string') return;
  const matches = (evidence.sessions ?? []).filter((row) => row.sid === record.attrs[0]);
  if (matches.length !== 1 || !Number.isFinite(evidence.generated)) return;
  const row = matches[0];
  const at =
    Number.isFinite(row.started_at) && row.started_at > 0 ? row.started_at : row.first_prompt_at;
  if (!Number.isFinite(at) || at <= 0) return;
  const seconds = Math.floor(Math.max(0, evidence.generated - at));
  const duration =
    seconds < 60
      ? `${seconds}s`
      : seconds < 3600
        ? `${Math.floor(seconds / 60)}m`
        : seconds < 86400
          ? `${Math.floor(seconds / 3600)}h ${Math.floor((seconds % 3600) / 60)}m`
          : `${Math.floor(seconds / 86400)}d ${Math.floor((seconds % 86400) / 3600)}h`;
  const identity = `${row.harness} · ${row.sid}`;
  const start = record.header.indexOf(identity);
  if (start < 0) return;
  let end = start + identity.length;
  const project = ` · ${row.project}`;
  const projectAt = row.project ? record.header.indexOf(project, end) : -1;
  if (projectAt >= 0) end = projectAt + project.length;
  else {
    const rate = /^ · [^·]*? \/m/.exec(record.header.slice(end));
    if (rate) end += rate[0].length;
  }
  record.header = `${record.header.slice(0, end)} · Started about ${duration} ago${record.header.slice(end)}`;
}
