import type { PromptCapacityPreview, SettingLimit, SettingsBody } from '../api/types';

/* What the Settings screen says about each limit, and the unit a reader types it in. The bounds and
   defaults are never here: they arrive with every answer, so a server that moves one moves the screen. A
   key this table does not know still draws, under its own name, so a new limit is never hidden. */
interface Copy {
  readonly label: string;
  readonly help: string;
  /** How many of the server's units make one of the reader's: the prompt is stored in bytes, typed in KB. */
  readonly scale: number;
  readonly unit: string;
}

const COPY: Readonly<Record<string, Copy>> = {
  analyze_prompt_bytes: {
    label: 'Prompt size',
    help: "The most one Analyze drift prompt may hold, including selected messages and evidence. A larger limit can include more text and take longer. This does not set the session outline's coverage or Summary's source coverage.",
    scale: 1024,
    unit: 'KB',
  },
  analyze_record_events: {
    label: 'Messages and checks kept',
    help: "How many of the session's messages and checks a press keeps after reading back to where your goal's window starts.",
    scale: 1,
    unit: 'messages and checks',
  },
  analyze_listed_checks: {
    label: 'Checks and files listed',
    help: "How many of the session's checks and written files a press lists for the model. The session page itself still lists 12.",
    scale: 1,
    unit: 'checks and files',
  },
  analyze_scan_megabytes: {
    label: 'Transcript scanned for checks',
    help: "How much of the session's transcript, and its subagents' transcripts, a press scans for the checks and files it lists. Subagents are where delegated work runs its tests. More reads more of that work, but takes longer and holds about five times as much in memory while the press runs.",
    scale: 1,
    unit: 'MB',
  },
};

export interface Field {
  readonly key: string;
  readonly label: string;
  readonly help: string | null;
  readonly unit: string;
  readonly scale: number;
  /** The value in force, the default and the inclusive range, all in the reader's unit. */
  readonly value: number;
  readonly fallback: number;
  readonly minimum: number;
  readonly maximum: number;
}

const COUNT = new Intl.NumberFormat('en-US', { maximumFractionDigits: 3 });

export const formatAmount = (value: number): string => COUNT.format(value);

/* The range shown is the range a whole number in the reader's unit can satisfy, so a bound that is not a
   whole KB rounds inward and nothing typed inside it is refused by the server. */
export function fieldsOf(body: SettingsBody): readonly Field[] {
  return body.limits.map((limit) => {
    const copy = COPY[limit.key];
    const scale = copy?.scale ?? 1;
    return {
      key: limit.key,
      label: copy?.label ?? limit.key,
      help: copy?.help ?? null,
      unit: copy?.unit ?? '',
      scale,
      value: (body.values[limit.key] ?? limit.default) / scale,
      fallback: limit.default / scale,
      minimum: Math.ceil(limit.minimum / scale),
      maximum: Math.floor(limit.maximum / scale),
    };
  });
}

/** The words an input starts with for a value: plain digits, because a grouped number is not one it parses. */
export const textOf = (value: number): string => String(value);

export const withUnit = (field: Field, value: number): string =>
  field.unit ? `${formatAmount(value)} ${field.unit}` : formatAmount(value);

export const rangeText = (field: Field): string =>
  `Allowed ${formatAmount(field.minimum)} to ${withUnit(field, field.maximum)}.`;

/** The server's value for what the reader typed, or the sentence saying why it is not one. */
export function parseDraft(
  field: Field,
  draft: string,
): { readonly ok: true; readonly value: number } | { readonly ok: false; readonly error: string } {
  const text = draft.trim();
  const number = /^-?\d+$/.test(text) ? Number(text) : Number.NaN;
  if (!Number.isSafeInteger(number) || number < field.minimum || number > field.maximum)
    return {
      ok: false,
      error: `Enter a whole number from ${formatAmount(field.minimum)} to ${withUnit(field, field.maximum)}.`,
    };
  return { ok: true, value: number * field.scale };
}

/* Only the keys whose words differ from the value in force are sent, so a Save never rewrites a setting
   the reader did not touch, including one shown in KB that is not a whole number of them. */
export function changedValues(
  fields: readonly Field[],
  drafts: Readonly<Record<string, string>>,
): { readonly values: Record<string, number>; readonly invalid: readonly string[] } {
  const values: Record<string, number> = {};
  const invalid: string[] = [];
  for (const field of fields) {
    const draft = drafts[field.key] ?? textOf(field.value);
    if (draft === textOf(field.value)) continue;
    const parsed = parseDraft(field, draft);
    if (parsed.ok) values[field.key] = parsed.value;
    else invalid.push(field.key);
  }
  return { values, invalid };
}

function isLimit(value: unknown): value is SettingLimit {
  if (typeof value !== 'object' || value === null) return false;
  const limit = value as Record<string, unknown>;
  return (
    typeof limit['key'] === 'string' &&
    ['default', 'minimum', 'maximum'].every((name) => Number.isSafeInteger(limit[name]))
  );
}

const CAPACITY_FIELDS = [
  'kind',
  'policy',
  'maximum_prompt_bytes',
  'window_tokens',
  'window_source',
  'generation_reserve_tokens',
  'cli_reserve_tokens',
  'estimated_system_tokens',
  'estimate_method',
  'fit_verified',
  'policy_verified',
  'configuration_reason',
  'reason',
  'can_lower_prompt_setting',
];
const CAPACITY_REASONS = [
  'estimated',
  'context-config',
  'context-no-room',
  'context-dynamic',
  'context-compaction',
  'context-fallback',
  'unavailable',
];
const CONFIGURATION_REASONS = [
  '',
  'context-config',
  'dynamic-policy',
  'compaction-policy-conflict',
  'fallback-policy-conflict',
];

const nonnegativeCount = (value: unknown): value is number =>
  typeof value === 'number' && Number.isSafeInteger(value) && value >= 0;
const oneOf = (value: unknown, choices: readonly string[]): boolean =>
  typeof value === 'string' && choices.includes(value);

/* Optional previews fail independently: an old server or one malformed route must not make the
   stored settings unusable. Accept only the closed estimate shape, never an input/fit receipt. */
function capacityPreview(value: unknown): PromptCapacityPreview | null {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) return null;
  const preview = value as Record<string, unknown>;
  if (
    Object.keys(preview).length !== CAPACITY_FIELDS.length ||
    !CAPACITY_FIELDS.every((key) => Object.hasOwn(preview, key)) ||
    preview['kind'] !== 'capacity-preview' ||
    preview['policy'] !== 'analyze-context-v1' ||
    preview['fit_verified'] !== false ||
    preview['policy_verified'] !== false ||
    typeof preview['can_lower_prompt_setting'] !== 'boolean' ||
    ![
      'maximum_prompt_bytes',
      'generation_reserve_tokens',
      'cli_reserve_tokens',
      'estimated_system_tokens',
    ].every((key) => nonnegativeCount(preview[key])) ||
    !(preview['window_tokens'] === null || nonnegativeCount(preview['window_tokens'])) ||
    !oneOf(preview['window_source'], ['documented', 'configured', 'unknown']) ||
    !oneOf(preview['estimate_method'], ['utf8-bytes-div-3', 'legacy-byte-cap']) ||
    !oneOf(preview['reason'], CAPACITY_REASONS) ||
    !oneOf(preview['configuration_reason'], CONFIGURATION_REASONS) ||
    (preview['reason'] === 'estimated' && preview['configuration_reason'] !== '') ||
    (preview['reason'] === 'estimated') !== Number(preview['maximum_prompt_bytes']) > 0
  )
    return null;
  return preview as unknown as PromptCapacityPreview;
}

/** An answer the screen can draw from, or null: a body missing either half is not one. */
export function settingsBody(body: unknown): SettingsBody | null {
  if (typeof body !== 'object' || body === null) return null;
  const { values, limits, capacities } = body as Record<string, unknown>;
  if (typeof values !== 'object' || values === null || Array.isArray(values)) return null;
  if (!Array.isArray(limits) || !limits.every(isLimit)) return null;
  const numbers = values as Record<string, unknown>;
  if (!limits.every((limit) => Number.isSafeInteger(numbers[limit.key]))) return null;
  const routes =
    typeof capacities === 'object' && capacities !== null && !Array.isArray(capacities)
      ? (capacities as Record<string, unknown>)
      : {};
  return {
    values: numbers as Record<string, number>,
    limits,
    capacities: {
      claude: capacityPreview(routes['claude']),
      codex: capacityPreview(routes['codex']),
    },
  };
}
