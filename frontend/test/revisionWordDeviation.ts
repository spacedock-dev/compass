/* The sentences that used to name a revision number now name times (docs/design-frontend-migration.md#held-to-recorded-answers).
   The recorded answers still carry the retired wording and are never re-recorded, and a time cannot be derived
   from a sentence that never held one, so a differential test masks the retired sentence and its replacement to
   one token on both sides and holds everything around them to the recording. The replacements themselves are
   held by the unit tests beside the code (`sessions/rows.test.ts`, `api/vocabulary.test.ts`). */

const MOMENT = String.raw`(?:\d{4}-\d{2}-\d{2} )?\d{2}:\d{2}`;

const RETIRED_AND_REPLACED: readonly RegExp[] = [
  // The stale sentence, once with revision numbers and now with times.
  /This (reading|raise) read revision \d+\. Revision \d+ is current, so it does not describe what you are asking for now\./g,
  new RegExp(
    String.raw`This (reading|raise) was made(?: at ${MOMENT})? against an earlier version of your intent\. You changed it(?: at ${MOMENT})?, so it does not describe what you are asking for now\.`,
    'g',
  ),
  // A list row's reading note.
  /read revision \d+(?:, \d+ is current)?/g,
  new RegExp(
    String.raw`read (?:at ${MOMENT}|your intent)(?:; intent changed(?: at ${MOMENT}| since))?`,
    'g',
  ),
  // The saved line under a goal: "revision 4 of 16 · typed 5m ago" is now "typed 5m ago", and the bound's
  // "older revisions dropped" is "older saves dropped".
  /revision \d+(?: of \d+|, \d+ kept)(?: · (?:typed|saved)(?: \d+[smhd])+ ago)?(?: · older revisions dropped)?/g,
  /(?:typed|saved)(?:(?: \d+[smhd])+ ago|, when not recorded)(?: · older saves dropped)?/g,
  // A raise's baseline.
  /read against revision \d+|the revision it read is not on record/g,
  /read against the intent as it stood then|the intent it read is not on record/g,
];

export function maskRevisionWords(text: string): string {
  return RETIRED_AND_REPLACED.reduce(
    (masked, pattern) =>
      masked.replace(pattern, (...found: unknown[]) => {
        const subject = found[1];
        return `[intent moved${typeof subject === 'string' ? `: ${subject}` : ''}]`;
      }),
    text,
  );
}
