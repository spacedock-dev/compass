import { act, fireEvent, render, screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { createApiClient, type FetchLike } from '../api/client';
import { ControlsProvider } from '../controls';
import { testControls } from '../controls/testControls';
import { SettingsScreen } from './SettingsView';

const LIMITS = [
  { key: 'analyze_prompt_bytes', default: 262144, minimum: 16384, maximum: 524288 },
  { key: 'analyze_record_events', default: 2000, minimum: 100, maximum: 20000 },
  { key: 'analyze_listed_checks', default: 200, minimum: 12, maximum: 2000 },
];
const DEFAULTS = {
  analyze_prompt_bytes: 262144,
  analyze_record_events: 2000,
  analyze_listed_checks: 200,
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
const production = (value = 524288, claude: unknown = PREVIEW): Answer => ({
  status: 200,
  body: {
    values: { ...DEFAULTS, analyze_prompt_bytes: value },
    limits: LIMITS.map((limit) =>
      limit.key === 'analyze_prompt_bytes'
        ? { ...limit, default: 524288, maximum: 2097152 }
        : limit,
    ),
    capacities: { claude, codex: PREVIEW },
  },
});

type Answer = { readonly status: number; readonly body: unknown } | 'offline';

/* A scripted server: each GET and POST takes the next answer in its queue, and every request is kept. */
function backend(gets: Answer[], posts: Answer[] = []) {
  const sent: { method: string; url: string; body: unknown }[] = [];
  const answer = (next: Answer | undefined) => {
    if (!next || next === 'offline') return Promise.reject(new Error('offline'));
    const text = typeof next.body === 'string' ? next.body : JSON.stringify(next.body);
    return Promise.resolve(new Response(text, { status: next.status }));
  };
  const fetch: FetchLike = (url, init) => {
    const method = init?.method ?? 'GET';
    sent.push({ method, url, body: init?.body ? JSON.parse(String(init.body)) : null });
    return answer(method === 'GET' ? gets.shift() : posts.shift());
  };
  return {
    client: createApiClient({ fetch }),
    sent,
    posts: () => sent.filter((r) => r.method === 'POST'),
  };
}

const ok = (values: Record<string, number> = DEFAULTS): Answer => ({
  status: 200,
  body: { values, limits: LIMITS },
});

const flush = async () => {
  await act(async () => {
    for (let turn = 0; turn < 12; turn += 1) await Promise.resolve();
  });
};

async function mount(server: ReturnType<typeof backend>) {
  const kit = testControls();
  return render(
    <ControlsProvider controls={kit.controls}>
      <SettingsScreen client={server.client} />
    </ControlsProvider>,
  );
}

const prompt = () => screen.getByRole('slider', { name: 'Prompt size' });
const open = async () => {
  const region = await screen.findByRole('region', { name: 'How much a progress check reads' });
  fireEvent.click(within(region).getByRole('button', { name: 'Customize' }));
  return within(region);
};

describe('the Settings screen', () => {
  it('saves and reopens 2048 KB independently of the route estimate, then resets it', async () => {
    const server = backend(
      [production(), production(2097152)],
      [production(2097152), production()],
    );
    const view = await mount(server);
    const card = await open();
    expect(prompt().getAttribute('aria-valuetext')).toBe('512 KB');
    expect(card.getAllByText('Estimated capacity: 512 KB.')).toHaveLength(2);
    expect(card.queryByText(/exceeds the Codex estimate/)).toBeNull();
    fireEvent.keyDown(prompt(), { key: 'End' });
    expect(server.posts()).toEqual([]);
    fireEvent.keyUp(prompt(), { key: 'End' });
    await flush();
    expect(server.posts()[0]?.body).toEqual({ values: { analyze_prompt_bytes: 2097152 } });
    expect(prompt().getAttribute('aria-valuetext')).toBe('2,048 KB');
    view.unmount();
    await mount(server);
    await open();
    expect(prompt().getAttribute('aria-valuetext')).toBe('2,048 KB');
    fireEvent.click(screen.getByRole('button', { name: 'Reset Prompt size' }));
    await flush();
    expect(prompt().getAttribute('aria-valuetext')).toBe('512 KB');
    expect(server.posts()[1]?.body).toEqual({ values: { analyze_prompt_bytes: null } });
  });

  it('keeps confirmed limits when reset answers with an empty receipt', async () => {
    const server = backend(
      [production(2097152)],
      [{ status: 200, body: { values: {}, limits: [] } }],
    );
    await mount(server);
    const card = await open();
    fireEvent.click(card.getByRole('button', { name: 'Reset Prompt size' }));
    await flush();
    expect(card.getByRole('status').textContent).toContain('Compass could not confirm the change.');
    expect(prompt().getAttribute('aria-valuetext')).toBe('2,048 KB');
    expect(card.queryByText('Limits saved.')).toBeNull();
  });

  it('posts null for each server limit when the reader resets all', async () => {
    const server = backend([ok({ ...DEFAULTS, analyze_record_events: 5000 })], [ok()]);
    await mount(server);
    const card = await open();
    fireEvent.click(card.getByRole('button', { name: 'Reset all to recommended' }));
    await flush();
    expect(server.posts()[0]?.body).toEqual({
      values: {
        analyze_prompt_bytes: null,
        analyze_record_events: null,
        analyze_listed_checks: null,
      },
    });
    expect(card.queryByText('Changed')).toBeNull();
  });

  it('shows the exact saved off-stop value when the reader first opens Customize', async () => {
    const server = backend([production(541696)]);
    await mount(server);
    const card = await open();
    expect(prompt().getAttribute('aria-valuetext')).toBe('529 KB');
    expect(card.getByText('Recommended: 512 KB')).toBeTruthy();
    expect(server.posts()).toEqual([]);
  });

  it('withholds settings while loading or unreadable, then lets the reader retry', async () => {
    const server = backend([{ status: 500, body: 'unreadable' }, ok()]);
    await mount(server);
    expect(screen.getByText('Reading the settings in force.')).toBeTruthy();
    expect(
      await screen.findByText('The prompt limits and update preference could not be read.'),
    ).toBeTruthy();
    expect(screen.queryByRole('slider')).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: 'Try again' }));
    await open();
    expect(prompt().getAttribute('aria-valuetext')).toBe('256 KB');
  });
});

describe('the daily release lookup switch', () => {
  const answer = (disabled: boolean): Answer => ({
    status: 200,
    body: {
      limits: LIMITS,
      values: DEFAULTS,
      update_check: { disabled, default_enabled: true, cli_disabled: false },
    },
  });
  const name = 'Look for new versions once a day';

  it('writes the inverse saved key and shows what the server confirms', async () => {
    const server = backend([answer(true)], [answer(false)]);
    await mount(server);
    const control = await screen.findByRole('switch', { name });
    expect(control.getAttribute('aria-checked')).toBe('false');
    fireEvent.click(control);
    await flush();
    expect(server.posts()).toEqual([
      { method: 'POST', url: '/api/settings', body: { values: { no_update_check: false } } },
    ]);
    expect(control.getAttribute('aria-checked')).toBe('true');
    expect(screen.queryByRole('button', { name: 'Save' })).toBeNull();
  });

  it('does not show an enabled switch when the server says the run cannot check', async () => {
    await mount(
      backend([
        {
          status: 200,
          body: {
            limits: LIMITS,
            values: DEFAULTS,
            update_check: { disabled: false, default_enabled: true, cli_disabled: true },
          },
        },
      ]),
    );
    expect(
      await screen.findByText('Update checks are off for this run (--no-update-check).'),
    ).toBeTruthy();
    expect(screen.queryByRole('switch', { name })).toBeNull();
  });
});
