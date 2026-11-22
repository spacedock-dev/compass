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
  }
  return projected;
}
