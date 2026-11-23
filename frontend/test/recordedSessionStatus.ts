/* 2026-11-23, docs/design-frontend-migration.md#held-to-recorded-answers
   The project rollups now use the displayed member states. Keep the total and the reported ends
   in the recorded comparisons. ProjectsQuietRollup and ProjectDisplayedStateRollup assert the
   subtotals that moved. */
export function omitProjectStateSubtotals(text: string): string {
  return text.replace(
    /(\d+ sessions?)((?: · \d+ (?:working|waiting on you|ended|quiet|in no counted state))+)/g,
    (_line, total: string, subtotals: string) =>
      total + (subtotals.match(/ · \d+ ended/)?.[0] ?? ''),
  );
}

/* Quiet requires a turn end. The retired page and its fixtures have no declared child waits,
   so the moving count can still be compared. Keep the set size and the partial-read count too. */
export function omitAttentionQuietSubtotals(text: string): string {
  return text.replace(
    /(The other \d+: )([^;]+)(; of these, \d+ partially read\.)/g,
    (_line, intro: string, counts: string, suffix: string) => {
      const kept = counts
        .split(' · ')
        .filter((word) => !/^\d+ (?:quiet|in no counted state)$/.test(word));
      return intro + (kept.join(' · ') || 'none') + suffix;
    },
  );
}

/* 2026-11-22, docs/design-frontend-migration.md#held-to-recorded-answers
   Project members embed the same observed rows as Sessions. Project only the retired
   outcome marker and the idle placeholder. Relationship and scan status have their own proofs. */
export function recordedSessionStatus(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(recordedSessionStatus);
  if (!value || typeof value !== 'object') return value;
  const row = value as Record<string, unknown>;
  const projected = Object.fromEntries(
    Object.entries(row).map(([key, item]) => [key, recordedSessionStatus(item)]),
  );
  if (Object.hasOwn(row, 'outcomeGlyph')) {
    delete projected['outcomeGlyph'];
    projected['outcomeIcon'] = row['isEnded']
      ? row['outcomeGlyph'] === '△'
        ? 'worth-a-look'
        : 'ended'
      : null;
    // The retired payloads never carried a declared child wait.
    projected['childWait'] = '';
    projected['scanOnly'] = false;
    if (row['nowText'] === 'quiet' && !row['outcomeKnown']) {
      projected['nowText'] = 'No recent activity';
    }
  } else if (Object.hasOwn(row, 'outcomeIcon')) {
    // Scan notice placement and availability are tested directly against acquisition evidence.
    projected['scanOnly'] = false;
    // Sessions renders this new spelling. Its mounted and terminal parity tests check the words.
    delete projected['nowWords'];
    delete projected['nowWordsKnown'];
  }
  if (
    projected['blockNote'] ===
    'Unconfirmed: no positive observation in 5m; prompt may still be standing'
  ) {
    projected['blockNote'] =
      'Unconfirmed: no positive observation in 5 minutes; prompt may still be standing';
  }
  return projected;
}
