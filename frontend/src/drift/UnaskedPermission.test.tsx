import { screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { driftBoard, json, mountDrift, press, readingPosts, ROUTE, POLICY } from './testing';

const CODEX = {
  ...ROUTE,
  provider: 'codex',
  label: 'Codex',
  words_destination: 'api',
  disclosure_parts: ['Your typed goal and your messages go to api.'],
};
const policy = (allowed: boolean) => ({
  ...POLICY,
  words: { codex: allowed },
  providers: { codex: false },
});
const payload = (allowed = false) => ({
  unasked: true,
  reading: policy(allowed),
  unasked_routes: { claude: CODEX },
});

describe('Unasked check permission', () => {
  it('shows the waiting cue and grants then revokes only on the toggle', async () => {
    const page = mountDrift({
      store: { goal_source: 'typed' },
      payload: payload(),
      routes: {
        '/api/reading': (request) => {
          const allowed = request.body?.['unasked_grant'] === true;
          page.state.data = driftBoard({
            store: { goal_source: 'typed' },
            payload: payload(allowed),
          });
          return json({ ok: true, reading: policy(allowed), produced: false });
        },
      },
    });
    await page.settle();
    expect(screen.getByText(/Unasked checks of this session are waiting/)).toBeTruthy();
    expect(readingPosts(page)).toHaveLength(0);
    await press(screen.getByRole('switch', { name: 'Allow Codex to run unasked checks' }));
    expect(screen.getByRole('switch', { name: /Codex/ }).getAttribute('aria-checked')).toBe('true');
    expect(readingPosts(page)[0]?.body).toMatchObject({
      unasked_grant: true,
      provider: 'codex',
      words_destination: 'api',
      press: true,
      observer_model: 1,
    });
    await press(screen.getByRole('switch', { name: 'Allow Codex to run unasked checks' }));
    expect(screen.getByRole('switch', { name: /Codex/ }).getAttribute('aria-checked')).toBe(
      'false',
    );
    expect(readingPosts(page)[1]?.body?.['unasked_grant']).toBe(false);
  });

  it('hides the toggle with the flag off and for the accepted Claude provider', async () => {
    const page = mountDrift({ payload: { ...payload(), unasked: false } });
    await page.settle();
    expect(screen.queryByRole('switch', { name: /Codex/ })).toBeNull();
    await page.poll(driftBoard({ payload: { unasked: true, unasked_routes: { claude: ROUTE } } }));
    expect(screen.queryByRole('switch', { name: /Codex/ })).toBeNull();
    expect(readingPosts(page)).toHaveLength(0);
  });

  it('names Claude Code and what each check sends when Claude Code runs unasked checks', async () => {
    const page = mountDrift({ payload: { unasked: true, unasked_routes: { claude: ROUTE } } });
    await page.settle();
    const notice = screen.getByRole('region', { name: 'Unasked checks by Claude Code' });
    expect(notice.textContent).toContain('Claude Code checks this session');
    expect(notice.textContent).toContain('Your saved words.');
    expect(notice.textContent).toContain('The agent messages.');
    expect(screen.queryByRole('switch', { name: /Codex/ })).toBeNull();
  });

  it('keeps the revoke switch for a stored Codex grant after Claude Code takes the route', async () => {
    const claudePolicy = { ...policy(true), providers: { codex: false } };
    const page = mountDrift({
      payload: { unasked: true, reading: claudePolicy, unasked_routes: { claude: ROUTE } },
      routes: {
        '/api/reading': () => {
          page.state.data = driftBoard({
            payload: { unasked: true, reading: policy(false), unasked_routes: { claude: ROUTE } },
          });
          return json({ ok: true, reading: policy(false), produced: false });
        },
      },
    });
    await page.settle();
    expect(screen.getByText(/though it does not check this session/)).toBeTruthy();
    const toggle = screen.getByRole('switch', { name: 'Allow Codex to run unasked checks' });
    expect(toggle.getAttribute('aria-checked')).toBe('true');
    await press(toggle);
    expect(readingPosts(page)[0]?.body).toMatchObject({ unasked_grant: false, provider: 'codex' });
    expect(screen.queryByRole('switch', { name: /Codex/ })).toBeNull();
    expect(screen.getByRole('region', { name: 'Unasked checks by Claude Code' })).toBeTruthy();
  });

  it('disables the toggle while paused and explains why', async () => {
    const page = mountDrift({
      payload: {
        ...payload(),
        reading: { ...policy(false), off: true, consent: false, reason: 'model-calls-paused' },
      },
    });
    await page.settle();
    expect((screen.getByRole('switch', { name: /Codex/ }) as HTMLButtonElement).disabled).toBe(
      true,
    );
    await press(screen.getByRole('switch', { name: /Codex/ }));
    expect(readingPosts(page)).toHaveLength(0);
  });

  it('directs Attention readers to the session toggle only for saved typed goals', async () => {
    const page = mountDrift({
      store: { goal_source: 'typed' },
      payload: payload(),
      hash: '#n=attention',
    });
    await page.settle();
    const cue = screen.getByRole('region', { name: 'Unasked checks waiting for permission' });
    expect(cue.textContent).toContain('Allow Codex to run unasked checks');
    expect(cue.textContent).toContain('none of them has been checked yet');
    await press(cue.querySelector('a'));
    expect(screen.getByRole('switch', { name: 'Allow Codex to run unasked checks' })).toBeTruthy();
  });
  it('does not ask Attention readers to grant checks for adopted goals or outcome lines alone', async () => {
    const page = mountDrift({
      hash: '#n=attention',
      store: { goal_source: 'first-prompt' },
      payload: payload(),
    });
    await page.settle();
    expect(
      screen.queryByRole('region', { name: 'Unasked checks waiting for permission' }),
    ).toBeNull();
    await page.poll(
      driftBoard({
        payload: payload(),
        store: { goal: '', lines: ['Tests pass'], goal_source: 'typed' },
      }),
    );
    expect(
      screen.queryByRole('region', { name: 'Unasked checks waiting for permission' }),
    ).toBeNull();
  });

  it('does not say a session checked before a revoke was never checked', async () => {
    const page = mountDrift({
      store: { goal_source: 'typed' },
      payload: payload(),
      hash: '#n=attention',
      session: { departure_checked: true },
    });
    await page.settle();
    const cue = screen.getByRole('region', { name: 'Unasked checks waiting for permission' });
    expect(cue.textContent).toContain('they are not being checked now');
    expect(cue.textContent).not.toContain('none of them has been checked');
  });
});
