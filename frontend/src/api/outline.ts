/* `sources.outline` on a focused `/api/project-context` answer: Compass's own grouping of one session's
   bounded record, one block per person message, made with no model call
   ([the contract](../../../docs/design-session-summary.md#bounds-and-focused-grouping)).

   Parsed rather than cast, because the card that draws it labels it as Compass's grouping: an answer that does
   not say `made_by: compass` and `basis: grouping` is not one, and is read as no outline at all. A field the
   card does not draw is not kept. */

export type OutlineState = 'ok' | 'unsupported' | 'unavailable' | 'stale';

export interface OutlineCheck {
  readonly factId: string;
  readonly title: string;
}

export interface OutlineBlock {
  /** The person message the block starts at, or null for work before the first prompt the read holds. */
  readonly prompt: {
    readonly factId: string;
    readonly title: string;
    readonly at: number | null;
  } | null;
  /** The session's first part. Always shown, even when the read's newest window begins after it. */
  readonly opening: boolean;
  /** The first part's read ended before the next prompt, so its counts are a floor. */
  readonly partial: boolean;
  readonly span: {
    readonly first: string;
    readonly last: string;
    readonly entries: number;
    readonly fromAt: number | null;
  };
  readonly counts: {
    readonly checks: number;
    /** Checks whose newest failed run in this part no later pass followed. */
    readonly checksFailed: number;
    /** Checks that failed in this part and passed on a later run: a red test that was fixed. */
    readonly checksFixed: number;
    readonly files: number;
    readonly agentMessages: number;
    readonly subagentEntries: number;
  };
  readonly failures: readonly OutlineCheck[];
  readonly folders: readonly { readonly folder: string; readonly files: number }[];
}

export interface OutlineCoverage {
  /* Where in the parent record the read began. Above zero means an older prefix was skipped; `starts_at` is
     not that signal, because the server sets it for any unread region, a time or byte stop included. */
  readonly startOffset: number;
  /** `read`, or `not_read` where the harness's agent words are not admitted. */
  readonly agentReplies: string;
  /** `read`, or `not_admitted` where the harness's checks and files are not admitted. */
  readonly checksAndFiles: string;
  readonly unread: readonly { readonly reason: string }[];
}

export interface Outline {
  readonly state: OutlineState;
  readonly reason: string | null;
  readonly coverage: OutlineCoverage | null;
  readonly blocks: readonly OutlineBlock[];
  readonly moreBlocks: number;
}

type Raw = Readonly<Record<string, unknown>>;
const STATES: readonly string[] = ['ok', 'unsupported', 'unavailable', 'stale'];

const record = (value: unknown): Raw | null =>
  value !== null && typeof value === 'object' && !Array.isArray(value) ? (value as Raw) : null;
const text = (value: unknown): string => (typeof value === 'string' ? value : '');
const time = (value: unknown): number | null =>
  typeof value === 'number' && Number.isFinite(value) && value > 0 ? value : null;
const count = (value: unknown): number =>
  typeof value === 'number' && Number.isInteger(value) && value >= 0 ? value : 0;
const list = (value: unknown): readonly Raw[] =>
  Array.isArray(value) ? value.map(record).filter((row): row is Raw => row !== null) : [];

function check(row: Raw): OutlineCheck | null {
  const factId = text(row['fact_id']);
  return factId ? { factId, title: text(row['title']) } : null;
}

function block(row: Raw): OutlineBlock | null {
  const span = record(row['span']);
  const first = text(span?.['first']);
  const last = text(span?.['last']);
  if (!span || !first || !last) return null;
  const prompt = record(row['prompt']);
  const counts = record(row['counts']) ?? {};
  return {
    prompt:
      prompt && text(prompt['fact_id'])
        ? { factId: text(prompt['fact_id']), title: text(prompt['title']), at: time(prompt['at']) }
        : null,
    opening: row['opening'] === true,
    partial: row['partial'] === true,
    span: {
      first,
      last,
      entries: count(span['entries']),
      fromAt: time(span['from_at']),
    },
    counts: {
      checks: count(counts['checks']),
      checksFailed: count(counts['checks_failed']),
      checksFixed: count(counts['checks_fixed']),
      files: count(counts['files']),
      agentMessages: count(counts['agent_messages']),
      subagentEntries: count(counts['subagent_entries']),
    },
    failures: list(row['failures'])
      .map(check)
      .filter((row): row is OutlineCheck => row !== null),
    folders: list(row['folders']).map((row) => ({
      folder: text(row['folder']),
      files: count(row['files']),
    })),
  };
}

function coverage(value: unknown): OutlineCoverage | null {
  const row = record(value);
  if (!row) return null;
  return {
    startOffset: count(row['start_offset']),
    agentReplies: text(row['agent_replies']),
    checksAndFiles: text(row['checks_and_files']),
    unread: list(row['unread']).map((region) => ({ reason: text(region['reason']) })),
  };
}

/** The outline a focused context answer carries, or null when it carries none or one not labelled as Compass's. */
export function parseOutline(context: unknown): Outline | null {
  const sources = record(record(context)?.['sources']);
  const raw = record(sources?.['outline']);
  if (!raw || raw['made_by'] !== 'compass' || raw['basis'] !== 'grouping') return null;
  const state = text(raw['state']);
  if (!STATES.includes(state)) return null;
  return {
    state: state as OutlineState,
    reason: text(raw['reason']) || null,
    coverage: coverage(raw['coverage']),
    // Non-ok answers hold no entries, whatever a malformed body says.
    blocks:
      state === 'ok'
        ? list(raw['blocks'])
            .map(block)
            .filter((row): row is OutlineBlock => row !== null)
        : [],
    moreBlocks: count(raw['more_blocks']),
  };
}
