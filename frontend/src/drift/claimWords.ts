import type { WorkEntry } from '../intent/work';

/* The words of `reading.CLAIMS_RULE`, which the model is told to compare with the record. The resolver cannot
   tell a claim's kind, so the page picks the cited message that holds one of them to quote. Keep the two lists
   equal; "passing" there is read here as its three forms. */
const CLAIM_WORDS =
  /\b(?:running|done|merged|pushed|deployed|passing|passes|passed|fixed|sent|filed)\b/i;

export function holdsClaimWord(text: string | null | undefined): boolean {
  return CLAIM_WORDS.test(String(text || ''));
}

/* The cited agent message the claims row quotes: the first holding a claim word, else the first cited. The
   rest stay listed beneath as context. */
export function claimMessage(said: readonly WorkEntry[]): WorkEntry | null {
  return said.find((entry) => holdsClaimWord(entry.summary)) ?? said[0] ?? null;
}
