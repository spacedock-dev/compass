import { describe, expect, it } from 'vitest';
import { mountDrift, ROUTE, textOf } from './testing';

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

const allowance = () => textOf('[data-next-reading-allowance]');

describe('the next Analyze prompt allowance', () => {
  it('follows the selected route on refresh without fetching Settings', async () => {
    const page = mountDrift({
      payload: { reading_routes: { claude: { ...ROUTE, capacity: PREVIEW } } },
    });
    await page.settle();
    await page.settle();
    expect(allowance()).toContain('Next Analyze prompt');
    expect(allowance()).toContain('Estimated allowance: 512 KB.');
    expect(allowance()).toContain('context window is unknown');
    expect(allowance()).toContain('do not confirm model availability or that a prompt will fit');
    expect(allowance()).toContain('not automatically shortened');
    await page.poll({
      ...(page.state.data as object),
      generated: 1100,
      reading_routes: {
        claude: {
          ...ROUTE,
          provider: 'codex',
          capacity: { ...PREVIEW, maximum_prompt_bytes: 262144 },
        },
      },
    });
    expect(allowance()).toContain('Estimated allowance: 256 KB.');
    expect(allowance()).not.toContain('512 KB');
    expect(page.state.requests.some((request) => request.path === '/api/settings')).toBe(false);
  });

  it.each([
    undefined,
    null,
    [],
    { ...PREVIEW, fit_verified: true },
    { ...PREVIEW, words: 'secret' },
  ])('keeps missing or malformed previews explicitly unknown (%#)', async (capacity) => {
    const page = mountDrift({
      payload: { reading_routes: { claude: { ...ROUTE, capacity } } },
    });
    await page.settle();
    await page.settle();
    expect(allowance()).toContain('Allowance unknown');
    expect(allowance()).not.toMatch(/0 KB|secret|refused before a model call/);
  });

  it.each([
    ['context-no-room', '', 'leaves no room'],
    ['context-config', 'context-config', 'settings could not be checked'],
    ['context-dynamic', 'dynamic-policy', 'policy can change'],
  ])(
    'explains %s without displaying zero as fit or lowering advice',
    async (reason, configuration_reason, words) => {
      const page = mountDrift({
        payload: {
          reading_routes: {
            claude: {
              ...ROUTE,
              capacity: { ...PREVIEW, maximum_prompt_bytes: 0, reason, configuration_reason },
            },
          },
        },
      });
      await page.settle();
      await page.settle();
      expect(allowance()).toContain(words);
      expect(allowance()).not.toMatch(/0 KB|0 bytes|[Ll]ower|[Rr]educe Prompt/);
    },
  );

  it('shows a tiny allowance in bytes without advising an impossible setting', async () => {
    const page = mountDrift({
      payload: {
        reading_routes: { claude: { ...ROUTE, capacity: { ...PREVIEW, maximum_prompt_bytes: 1 } } },
      },
    });
    await page.settle();
    await page.settle();
    expect(allowance()).toContain('Estimated allowance: 1 byte.');
    expect(allowance()).not.toMatch(/0 KB|[Ll]ower|[Rr]educe Prompt/);
  });
});
