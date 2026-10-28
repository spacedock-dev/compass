import { act, fireEvent, render, screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { createApiClient, type FetchLike } from '../api/client';
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

const field = (name: RegExp) => screen.getByRole('spinbutton', { name }) as HTMLInputElement;
const prompt = () => field(/Prompt size/);
const kept = () => field(/Messages and checks kept/);
const listed = () => field(/Checks and files listed/);
const outcome = () => document.querySelector('[data-next-settings-outcome]')?.textContent ?? '';

async function mount(server: ReturnType<typeof backend>) {
  render(<SettingsScreen client={server.client} />);
  await flush();
}

describe('the Settings screen', () => {
  it('says it is reading, then draws every limit from the answer in the reader’s unit', async () => {
    const server = backend([ok({ ...DEFAULTS, analyze_record_events: 5000 })]);
    render(<SettingsScreen client={server.client} />);
    expect(screen.getByText('Reading the settings in force.')).toBeTruthy();
    await flush();
    expect(server.sent).toEqual([{ method: 'GET', url: '/api/settings', body: null }]);
    expect(prompt().value).toBe('256');
    expect(kept().value).toBe('5000');
    expect(listed().value).toBe('200');
    expect(prompt().min).toBe('16');
    expect(prompt().max).toBe('512');
    const bounds = document.getElementById(
      prompt().getAttribute('aria-describedby')?.split(' ')[1] ?? '',
    );
    expect(bounds?.textContent).toBe('In force: 256 KB. Default 256 KB. Allowed 16 to 512 KB.');
    expect(prompt().getAttribute('aria-describedby')?.split(' ')).toHaveLength(2);
    expect(screen.getByText(/The session page itself still lists 12/)).toBeTruthy();
    // Only the changed one offers its default back, and so does the screen as a whole.
    expect(screen.getAllByRole('button', { name: /^Restore default/ })).toHaveLength(1);
    expect(
      screen.getByRole('button', { name: 'Restore default (2,000 messages and checks)' }),
    ).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Restore all defaults' })).toBeTruthy();
  });

  it('reads its bounds from the answer, never from a copy of its own', async () => {
    const limits = LIMITS.map((limit) =>
      limit.key === 'analyze_listed_checks'
        ? { ...limit, minimum: 50, maximum: 60, default: 55 }
        : limit,
    );
    const server = backend([
      { status: 200, body: { values: { ...DEFAULTS, analyze_listed_checks: 55 }, limits } },
    ]);
    await mount(server);
    expect(listed().min).toBe('50');
    expect(listed().max).toBe('60');
    fireEvent.change(listed(), { target: { value: '61' } });
    expect(screen.getByText('Enter a whole number from 50 to 60 checks and files.')).toBeTruthy();
  });

  it('refuses a value outside its range or not whole, inline, naming the range', async () => {
    const server = backend([ok()]);
    await mount(server);
    fireEvent.change(kept(), { target: { value: '99' } });
    const message = 'Enter a whole number from 100 to 20,000 messages and checks.';
    expect(screen.getByText(message)).toBeTruthy();
    expect(kept().getAttribute('aria-invalid')).toBe('true');
    expect(kept().getAttribute('aria-describedby')).toContain(`${kept().id}-error`);
    fireEvent.change(kept(), { target: { value: '150.5' } });
    expect(screen.getByText(message)).toBeTruthy();
    fireEvent.change(kept(), { target: { value: '' } });
    expect(screen.getByText(message)).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    await flush();
    expect(server.posts()).toEqual([]);
    expect(outcome()).toBe('Nothing was saved. Correct the value marked below first.');
    expect(document.activeElement).toBe(kept());
    fireEvent.change(kept(), { target: { value: '150' } });
    expect(screen.queryByText(message)).toBeNull();
    expect(kept().getAttribute('aria-invalid')).toBeNull();
  });

  it('sends only what changed, in the server’s unit, and redraws from the answer', async () => {
    const answered = { ...DEFAULTS, analyze_prompt_bytes: 524288, analyze_listed_checks: 400 };
    const server = backend([ok()], [ok(answered)]);
    await mount(server);
    fireEvent.change(prompt(), { target: { value: '512' } });
    fireEvent.change(listed(), { target: { value: '300' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    await flush();
    expect(server.posts()).toEqual([
      {
        method: 'POST',
        url: '/api/settings',
        body: { values: { analyze_prompt_bytes: 524288, analyze_listed_checks: 300 } },
      },
    ]);
    // The answer, not what was sent, is what the screen now shows.
    expect(prompt().value).toBe('512');
    expect(listed().value).toBe('400');
    expect(kept().value).toBe('2000');
    expect(outcome()).toBe('Saved. The next Analyze drift press reads with these limits.');
    expect(
      screen.getByText(
        'In force: 400 checks and files. Default 200 checks and files. Allowed 12 to 2,000 checks and files.',
      ),
    ).toBeTruthy();
  });

  it('sends nothing when nothing changed', async () => {
    const server = backend([ok()]);
    await mount(server);
    fireEvent.change(kept(), { target: { value: '2000' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    await flush();
    expect(server.posts()).toEqual([]);
    expect(outcome()).toBe('Nothing changed, so nothing was sent.');
  });

  it('restores one default with a null for that key alone, and keeps another field’s unsaved edit', async () => {
    const changed = { ...DEFAULTS, analyze_record_events: 5000 };
    const server = backend([ok(changed)], [ok()]);
    await mount(server);
    fireEvent.change(listed(), { target: { value: '300' } });
    fireEvent.click(
      screen.getByRole('button', { name: 'Restore default (2,000 messages and checks)' }),
    );
    await flush();
    expect(server.posts().map((request) => request.body)).toEqual([
      { values: { analyze_record_events: null } },
    ]);
    expect(kept().value).toBe('2000');
    expect(listed().value).toBe('300');
    expect(outcome()).toBe(
      'Messages and checks kept is back to its default, 2,000 messages and checks.',
    );
    expect(screen.queryByRole('button', { name: /^Restore default/ })).toBeNull();
  });

  it('restores every default with a null for every key', async () => {
    const changed = {
      analyze_prompt_bytes: 32768,
      analyze_record_events: 5000,
      analyze_listed_checks: 20,
    };
    const server = backend([ok(changed)], [ok()]);
    await mount(server);
    expect(prompt().value).toBe('32');
    fireEvent.click(screen.getByRole('button', { name: 'Restore all defaults' }));
    await flush();
    expect(server.posts().map((request) => request.body)).toEqual([
      {
        values: {
          analyze_prompt_bytes: null,
          analyze_record_events: null,
          analyze_listed_checks: null,
        },
      },
    ]);
    expect([prompt().value, kept().value, listed().value]).toEqual(['256', '2000', '200']);
    expect(outcome()).toBe('Every limit is back to its default.');
    expect(screen.queryByRole('button', { name: 'Restore all defaults' })).toBeNull();
  });

  it.each([
    [
      { status: 400, body: '<html>analyze_prompt_bytes is not a setting</html>' } as Answer,
      'The server refused these values, so nothing was saved. Each must be a whole number inside its range.',
    ],
    [
      { status: 503, body: '<html>the settings store could not be written</html>' } as Answer,
      'The settings could not be written, so nothing changed. Try again.',
    ],
    [{ status: 500, body: '' } as Answer, 'The server answered 500, so nothing was saved.'],
    ['offline' as Answer, 'The server could not be reached, so nothing was saved.'],
    [
      { status: 200, body: { values: {} } } as Answer,
      'The server answered in a form this page cannot read. Reload to see the values in force.',
    ],
  ])('keeps what was typed when a save is refused (%#)', async (refusal, words) => {
    const server = backend([ok()], [refusal]);
    await mount(server);
    fireEvent.change(kept(), { target: { value: '3000' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    await flush();
    expect(server.posts()).toHaveLength(1);
    expect(outcome()).toBe(words);
    expect(kept().value).toBe('3000');
    // The value in force is still the one the server last answered.
    expect(screen.getByText(/In force: 2,000 messages and checks/)).toBeTruthy();
  });

  it('holds the other presses while one is in flight', async () => {
    let release: (response: Response) => void = () => undefined;
    const sent: string[] = [];
    const fetch: FetchLike = (_url, init) => {
      if (init?.method !== 'POST')
        return Promise.resolve(
          new Response(
            JSON.stringify({ values: { ...DEFAULTS, analyze_listed_checks: 20 }, limits: LIMITS }),
          ),
        );
      sent.push(String(init.body));
      return new Promise((resolve) => {
        release = resolve;
      });
    };
    render(<SettingsScreen client={createApiClient({ fetch })} />);
    await flush();
    fireEvent.change(kept(), { target: { value: '3000' } });
    const save = screen.getByRole('button', { name: 'Save' });
    fireEvent.click(save);
    await flush();
    expect(save.getAttribute('aria-busy')).toBe('true');
    expect(within(save).getByText('Saving…')).toBeTruthy();
    expect(
      (screen.getByRole('button', { name: 'Restore all defaults' }) as HTMLButtonElement).disabled,
    ).toBe(true);
    fireEvent.click(save);
    fireEvent.submit(save.closest('form') as HTMLFormElement);
    await flush();
    expect(sent).toHaveLength(1);
    release(
      new Response(
        JSON.stringify({
          values: { ...DEFAULTS, analyze_record_events: 3000, analyze_listed_checks: 20 },
          limits: LIMITS,
        }),
      ),
    );
    await flush();
    expect(save.getAttribute('aria-busy')).toBeNull();
    expect(kept().value).toBe('3000');
  });

  it('says a failed read failed, and reads again on Try again', async () => {
    const server = backend([
      { status: 500, body: '' },
      { status: 200, body: { values: {}, limits: 'x' } },
      ok(),
    ]);
    await mount(server);
    expect(screen.getByText('The settings could not be read, so none are shown.')).toBeTruthy();
    expect(screen.queryByRole('spinbutton')).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: 'Try again' }));
    await flush();
    // A body without both halves is not one the screen can draw from.
    expect(screen.getByText('The settings could not be read, so none are shown.')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Try again' }));
    await flush();
    expect(prompt().value).toBe('256');
    expect(server.sent.filter((request) => request.method === 'GET')).toHaveLength(3);
  });

  it('draws a limit it has no words for under its own name', async () => {
    const limits = [...LIMITS, { key: 'future_limit', default: 5, minimum: 1, maximum: 9 }];
    const server = backend([
      { status: 200, body: { values: { ...DEFAULTS, future_limit: 5 }, limits } },
    ]);
    await mount(server);
    const future = screen.getByRole('spinbutton', { name: 'future_limit' }) as HTMLInputElement;
    expect(future.value).toBe('5');
    expect(screen.getByText('In force: 5. Default 5. Allowed 1 to 9.')).toBeTruthy();
  });

  it('abandons a write still in flight when the screen goes away', async () => {
    const fetch: FetchLike = (_url, init) =>
      init?.method === 'POST'
        ? new Promise(() => undefined)
        : Promise.resolve(new Response(JSON.stringify({ values: DEFAULTS, limits: LIMITS })));
    const view = render(<SettingsScreen client={createApiClient({ fetch })} />);
    await flush();
    fireEvent.change(kept(), { target: { value: '3000' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    await flush();
    view.unmount();
    await flush();
    expect(document.querySelector('[data-next-view-body="settings"]')).toBeNull();
  });
});
