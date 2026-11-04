import type { PromptCapacityPreview } from './types';

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

/* An absent or malformed route preview stays unknown. Accept only the closed estimate shape,
   never an input/fit receipt; neither consumer derives policy from these display fields. */
export function capacityPreview(value: unknown): PromptCapacityPreview | null {
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

const COUNT = new Intl.NumberFormat('en-US', { maximumFractionDigits: 3 });
const formatAmount = (value: number): string => COUNT.format(value);

export function allowanceText(preview: PromptCapacityPreview | null | undefined): string {
  if (!preview) return 'Allowance unknown. This server did not provide a usable estimate.';
  switch (preview.reason) {
    case 'estimated': {
      const bytes = preview.maximum_prompt_bytes;
      const amount =
        bytes < 1024
          ? `${formatAmount(bytes)} ${bytes === 1 ? 'byte' : 'bytes'}`
          : `${formatAmount(bytes / 1024)} KB`;
      return `Estimated allowance: ${amount}.`;
    }
    case 'context-no-room':
      return 'The current context configuration leaves no room for this reading. Choose a larger context window.';
    case 'context-dynamic':
      return 'This route’s policy can change when it starts, so its allowance cannot be established. Check its managed settings or choose another route.';
    case 'context-config':
      return 'The route’s context settings could not be checked. Check the managed settings before trying Analyze.';
    case 'context-compaction':
      return 'Managed settings conflict with keeping compaction off for Analyze. Ask your administrator to resolve the conflict.';
    case 'context-fallback':
      return 'Managed settings conflict with keeping automatic model switching off for Analyze. Ask your administrator to resolve the conflict.';
    case 'unavailable':
      return 'Allowance unknown. No reading route is selected.';
  }
}
