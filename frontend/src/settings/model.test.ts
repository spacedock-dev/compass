import { describe, expect, it } from 'vitest';
import { settingsBody } from './model';

const SETTINGS = {
  values: { analyze_prompt_bytes: 2097152 },
  limits: [{ key: 'analyze_prompt_bytes', default: 524288, minimum: 16384, maximum: 2097152 }],
};
const PREVIEW = {
  kind: 'capacity-preview',
  policy: 'analyze-context-v1',
  maximum_prompt_bytes: 524288,
  window_tokens: null,
  window_source: 'unknown',
  generation_reserve_tokens: 128000,
  cli_reserve_tokens: 16384,
  estimated_system_tokens: 0,
  estimate_method: 'legacy-byte-cap',
  fit_verified: false,
  policy_verified: false,
  configuration_reason: '',
  reason: 'estimated',
  can_lower_prompt_setting: true,
};

describe('optional Settings route estimates', () => {
  it('keeps validated allowances separate from the saved prompt ceiling', () => {
    const body = settingsBody({ ...SETTINGS, capacities: { claude: PREVIEW, codex: PREVIEW } });
    expect(body?.capacities?.claude).toEqual(PREVIEW);
    expect(body?.capacities?.codex).toEqual(PREVIEW);
    expect(body?.values['analyze_prompt_bytes']).toBe(2097152);
  });

  it.each([
    null,
    [],
    { ...PREVIEW, kind: 'actual-input' },
    { ...PREVIEW, maximum_prompt_bytes: -1 },
    { ...PREVIEW, maximum_prompt_bytes: 1.5 },
    { ...PREVIEW, maximum_prompt_bytes: Number.MAX_SAFE_INTEGER + 1 },
    { ...PREVIEW, fit_verified: true },
    { ...PREVIEW, policy_verified: true },
    { ...PREVIEW, reason: 'private sentinel' },
    { ...PREVIEW, configuration_reason: 'private sentinel' },
    { ...PREVIEW, configuration_reason: 'dynamic-policy' },
    { ...PREVIEW, policy: 'future-unverified-policy' },
    { ...PREVIEW, maximum_prompt_bytes: 0 },
    { ...PREVIEW, window_tokens: -1 },
    { ...PREVIEW, words: 'private sentinel' },
    { ...PREVIEW, can_lower_prompt_setting: 'yes' },
    { ...PREVIEW, reason: ['estimated'] },
    { ...PREVIEW, configuration_reason: [] },
    { ...PREVIEW, window_source: ['unknown'] },
    { ...PREVIEW, estimate_method: ['legacy-byte-cap'] },
  ])('keeps settings and the other provider usable when one preview is malformed (%#)', (bad) => {
    const body = settingsBody({ ...SETTINGS, capacities: { claude: bad, codex: PREVIEW } });
    expect(body?.values).toEqual(SETTINGS.values);
    expect(body?.capacities?.claude).toBeNull();
    expect(body?.capacities?.codex).toEqual(PREVIEW);
  });

  it('treats absent legacy previews as unknown without changing their bounds', () => {
    const body = settingsBody(SETTINGS);
    expect(body?.capacities).toEqual({ claude: null, codex: null });
    expect(body?.limits).toEqual(SETTINGS.limits);
  });

  it('keeps a measured zero-window refusal distinct from an unknown allowance', () => {
    const preview = {
      ...PREVIEW,
      maximum_prompt_bytes: 0,
      window_tokens: 0,
      window_source: 'configured',
      estimate_method: 'utf8-bytes-div-3',
      reason: 'context-no-room',
      can_lower_prompt_setting: false,
    };
    expect(
      settingsBody({ ...SETTINGS, capacities: { claude: preview } })?.capacities?.claude,
    ).toEqual(preview);
  });
});
