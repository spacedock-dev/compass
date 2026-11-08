import overtakenReply from '../../test/fixtures/client-contract/reading-unasked-revoke-overtaken.json';
import regrantedBoard from '../../test/fixtures/client-contract/data-unasked-regranted.json';
import dormantBoard from '../../test/fixtures/client-contract/data-unasked-dormant.json';
import revokedBoard from '../../test/fixtures/client-contract/data-unasked-revoked.json';
import revokeReply from '../../test/fixtures/client-contract/reading-unasked-revoked.json';
import { screen, within } from '@testing-library/react';
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

const unavailableNote =
  'Compass cannot run unasked checks for this harness because it has no session record reader.';
const unavailableRoute = {
  provider: '',
  reason: 'no-record-reader',
  note: unavailableNote,
  disclosure_parts: [],
};
const harnessPayload = (harness: string, route = unavailableRoute, allowed = false) => ({
  unasked: true,
  reading: policy(allowed),
  unasked_routes: { [harness]: route },
});

describe('A session without a record reader', () => {
  it.each(['gemini', 'copilot', 'cursor', 'opencode', 'goose', 'droid'])(
    'tells a reader why %s cannot run unasked checks and never asks for permission',
    async (harness) => {
      const page = mountDrift({
        hash: `#n=session:alpha%2Fapp:${harness}:s1`,
        session: { harness },
        store: { goal_source: 'typed' },
        payload: harnessPayload(harness),
      });
      await page.settle();
      expect(screen.getByText(unavailableNote)).toBeTruthy();
      expect(screen.queryByRole('switch', { name: /Codex/ })).toBeNull();
      await page.go('#n=attention');
      expect(
        screen.queryByRole('region', { name: 'Unasked checks waiting for permission' }),
      ).toBeNull();
      expect(readingPosts(page)).toHaveLength(0);
    },
  );

  it.each(['pi', 'antigravity'])(
    'still offers a reader Codex permission for %s in Attention and Drift',
    async (harness) => {
      const page = mountDrift({
        hash: '#n=attention',
        session: { harness },
        store: { goal_source: 'typed' },
        payload: { unasked: true, reading: policy(false), unasked_routes: { [harness]: CODEX } },
      });
      await page.settle();
      const cue = screen.getByRole('region', { name: 'Unasked checks waiting for permission' });
      await press(cue.querySelector('a'));
      expect(screen.getByRole('switch', { name: /Codex/ }).getAttribute('aria-checked')).toBe(
        'false',
      );
      expect(readingPosts(page)).toHaveLength(0);
    },
  );

  it('lets a reader revoke stored Codex coverage beside the unavailable explanation', async () => {
    const page = mountDrift({
      hash: '#n=session:alpha%2Fapp:gemini:s1',
      session: { harness: 'gemini' },
      payload: harnessPayload('gemini', unavailableRoute, true),
      routes: {
        '/api/reading': () => {
          page.state.data = driftBoard({
            session: { harness: 'gemini' },
            payload: harnessPayload('gemini'),
          });
          return json({ ok: true, reading: policy(false), produced: false });
        },
      },
    });
    await page.settle();
    expect(screen.getByText(unavailableNote)).toBeTruthy();
    const toggle = screen.getByRole('switch', { name: /Codex/ });
    expect(toggle.getAttribute('aria-checked')).toBe('true');
    await press(toggle);
    expect(readingPosts(page)[0]?.body).toMatchObject({ unasked_grant: false, provider: 'codex' });
    expect(screen.queryByRole('switch', { name: /Codex/ })).toBeNull();
    expect(screen.getByText(unavailableNote)).toBeTruthy();
  });

  it('removes an obsolete grant offer when a reader receives an unavailable route on refresh', async () => {
    const page = mountDrift({ store: { goal_source: 'typed' }, payload: payload() });
    await page.settle();
    expect(screen.getByRole('switch', { name: /Codex/ })).toBeTruthy();
    await page.poll(
      driftBoard({ store: { goal_source: 'typed' }, payload: harnessPayload('claude') }),
    );
    expect(screen.getByText(unavailableNote)).toBeTruthy();
    expect(screen.queryByRole('switch', { name: /Codex/ })).toBeNull();
    expect(readingPosts(page)).toHaveLength(0);
  });

  it('explains to a reader why an obsolete grant press was refused', async () => {
    const page = mountDrift({
      payload: payload(),
      routes: {
        '/api/reading': () => json({ ok: false, reason: 'no-record-reader' }, 409),
      },
    });
    await page.settle();
    await press(screen.getByRole('switch', { name: /Codex/ }));
    expect(
      within(screen.getByRole('region', { name: 'Unasked checks' })).getByRole('status')
        .textContent,
    ).toContain(unavailableNote);
  });
});

const dormantPolicy = dormantBoard.response.body.reading;
const revokedPolicy = revokedBoard.response.body.reading;
const dormantNote =
  'Your saved Codex permission does not apply now because where your words go has changed.';

describe('A reader with a Codex grant saved for an earlier destination', () => {
  it.each([undefined, '', 37])(
    'still sees how to revoke when the server note is %s',
    async (note) => {
      const page = mountDrift({
        payload: {
          ...payload(),
          reading: { ...dormantPolicy, dormant: { codex: note } },
        },
      });
      await page.settle();
      const card = screen.getByRole('region', { name: 'Unasked checks' });
      expect(Array.from(card.querySelectorAll('p'), (paragraph) => paragraph.textContent)).toEqual([
        'Turn the switch off to revoke it. You can then allow Codex again for where your words go now.',
      ]);
    },
  );

  it.each([
    ['a session with no provider', {}],
    ['an unreadable session', unavailableRoute],
    ['a Claude-routed session', ROUTE],
    ['a Codex-routed session', CODEX],
  ])('can revoke the saved grant from %s', async (_name, route) => {
    const nextPayload = {
      unasked: true,
      reading: revokedPolicy,
      unasked_routes: { claude: route },
    };
    const page = mountDrift({
      store: { goal_source: 'typed' },
      payload: { ...nextPayload, reading: dormantPolicy },
      routes: {
        '/api/reading': () => {
          page.state.data = driftBoard({ store: { goal_source: 'typed' }, payload: nextPayload });
          return json(revokeReply.response.body);
        },
      },
    });
    await page.settle();
    const toggle = screen.getByRole('switch', { name: /Allow Codex/ });
    expect(toggle.getAttribute('aria-checked')).toBe('true');
    expect(screen.getByText(dormantNote).textContent).toBe(dormantNote);
    expect(
      screen.getByText(
        route === CODEX
          ? 'Turn the switch off to revoke it. You can then allow Codex again for where your words go now.'
          : 'Turn the switch off to revoke it.',
        { exact: true },
      ),
    ).toBeTruthy();
    if (route !== CODEX) expect(screen.queryByText(/You can then allow Codex again/)).toBeNull();
    expect(screen.queryByText(/allow it again/i)).toBeNull();
    expect(screen.queryByText(/This permission covers every session/)).toBeNull();
    if (route === unavailableRoute) expect(screen.getByText(unavailableNote)).toBeTruthy();
    if (route === ROUTE)
      expect(screen.getByRole('region', { name: 'Unasked checks by Claude Code' })).toBeTruthy();
    await press(toggle);
    expect(readingPosts(page)).toHaveLength(1);
    expect(readingPosts(page)[0]?.body).toMatchObject({ unasked_grant: false, provider: 'codex' });
    expect(readingPosts(page).some((post) => post.body?.['unasked_grant'] === true)).toBe(false);
    expect(screen.queryByText(dormantNote)).toBeNull();
    if (route === CODEX)
      expect(screen.getByRole('switch', { name: /Allow Codex/ }).getAttribute('aria-checked')).toBe(
        'false',
      );
    else expect(screen.queryByRole('switch', { name: /Allow Codex/ })).toBeNull();
  });

  it.each([
    ['dormant', dormantPolicy],
    ['covered', policy(true)],
  ])('is not invited by Attention to grant again while the grant is %s', async (_name, reading) => {
    const page = mountDrift({
      hash: '#n=attention',
      store: { goal_source: 'typed' },
      payload: { ...payload(), reading },
    });
    await page.settle();
    expect(
      screen.queryByRole('region', { name: 'Unasked checks waiting for permission' }),
    ).toBeNull();
    expect(readingPosts(page)).toHaveLength(0);
  });

  it('still sees current coverage when only the requested content changed', async () => {
    const page = mountDrift({
      payload: {
        ...payload(true),
        reading: {
          ...policy(true),
          rebind: {
            codex: 'What a reading sends has changed since you allowed this, so allow it again.',
          },
          dormant: {},
        },
      },
    });
    await page.settle();
    expect(screen.getByRole('switch', { name: /Allow Codex/ }).getAttribute('aria-checked')).toBe(
      'true',
    );
    expect(screen.getByText(/This permission covers every session/)).toBeTruthy();
    expect(screen.queryByText(dormantNote)).toBeNull();
  });
});

describe('A reader following permission changes across board refreshes', () => {
  it('a reader hears the returned grant when another reader overtakes their revoke', async () => {
    const page = mountDrift({
      payload: { ...payload(), reading: dormantPolicy },
      routes: { '/api/reading': () => json(overtakenReply.response.body) },
    });
    await page.settle();
    page.state.routes['/api/data'] = () => json({}, 503);
    await press(screen.getByRole('switch', { name: /Allow Codex/ }));
    expect(readingPosts(page)[0]?.body?.['unasked_grant']).toBe(false);
    expect(screen.getByRole('switch', { name: /Allow Codex/ }).getAttribute('aria-checked')).toBe(
      'true',
    );
    expect(screen.getByText('Codex permission for unasked checks granted.')).toBeTruthy();
    expect(screen.queryByText('Codex permission for unasked checks revoked.')).toBeNull();
  });

  it.each([
    [
      409,
      { ok: false, reason: 'destination-changed' },
      'Where Codex sends your words changed. Check the destination shown here and try again.',
    ],
    [500, null, 'Permission could not be confirmed. Refresh before trying again.'],
  ])(
    'a reader sees the %s answer after an unrelated board arrives mid-grant',
    async (status, body, message) => {
      const page = mountDrift({
        payload: payload(),
        routes: { '/api/reading': () => 'hold' },
      });
      await page.settle();
      await press(screen.getByRole('switch', { name: /Allow Codex/ }));
      await page.poll(
        driftBoard({
          payload: payload(),
          session: { title: 'An unrelated wake refreshed the board' },
        }),
      );
      page.state.routes['/api/data'] = () => json({}, 503);
      await page.release('/api/reading', json(body, status));
      expect(
        within(screen.getByRole('region', { name: 'Unasked checks' })).getByRole('status')
          .textContent,
      ).toBe(message);
      expect(screen.getByRole('switch', { name: /Allow Codex/ }).getAttribute('aria-checked')).toBe(
        'false',
      );
    },
  );

  it('a reader sees the revoke after an older in-flight board arrives and refresh fails', async () => {
    const page = mountDrift({
      store: { goal_source: 'typed' },
      payload: { ...payload(), reading: dormantPolicy },
      routes: { '/api/reading': () => 'hold' },
    });
    await page.settle();
    await press(screen.getByRole('switch', { name: /Allow Codex/ }));
    // This is the board collected before the revoke, delivered while its reply is held.
    page.state.routes['/api/data'] = () =>
      new Response(
        JSON.stringify(
          driftBoard({
            store: { goal_source: 'typed' },
            payload: { ...payload(), reading: dormantPolicy },
          }),
        ),
        { headers: dormantBoard.response.headers },
      );
    await page.poll(page.state.data);
    page.state.routes['/api/data'] = () => json({}, 503);
    await page.release('/api/reading', json(revokeReply.response.body));
    expect(screen.getByRole('switch', { name: /Allow Codex/ }).getAttribute('aria-checked')).toBe(
      'false',
    );
    expect(screen.getByText('Codex permission for unasked checks revoked.')).toBeTruthy();
    await page.go('#n=attention');
    expect(
      screen.getByRole('region', { name: 'Unasked checks waiting for permission' }),
    ).toBeTruthy();
    expect(screen.queryByRole('region', { name: 'Unasked checks cannot run' })).toBeNull();
  });

  it('keeps the newer grant when a late revoke arrives and the next refresh fails', async () => {
    const page = mountDrift({
      store: { goal_source: 'typed' },
      payload: { ...payload(), reading: dormantPolicy },
      routes: { '/api/reading': () => 'hold' },
    });
    await page.settle();
    await press(screen.getByRole('switch', { name: /Allow Codex/ }));
    expect(readingPosts(page)[0]?.body?.['unasked_grant']).toBe(false);
    page.state.routes['/api/data'] = () =>
      new Response(
        JSON.stringify(
          driftBoard({
            store: { goal_source: 'typed' },
            payload: { ...payload(), reading: regrantedBoard.response.body.reading },
          }),
        ),
        { headers: regrantedBoard.response.headers },
      );
    await page.poll(page.state.data);
    expect(screen.getByRole('switch', { name: /Allow Codex/ }).getAttribute('aria-checked')).toBe(
      'true',
    );
    page.state.routes['/api/data'] = () => json({}, 503);
    await page.release('/api/reading', json(revokeReply.response.body));
    expect(screen.getByRole('switch', { name: /Allow Codex/ }).getAttribute('aria-checked')).toBe(
      'true',
    );
    expect(screen.queryByText('Codex permission for unasked checks revoked.')).toBeNull();
    await page.go('#n=attention');
    expect(
      screen.queryByRole('region', { name: 'Unasked checks waiting for permission' }),
    ).toBeNull();
    expect(screen.queryByRole('region', { name: 'Unasked checks cannot run' })).toBeNull();
  });

  it('sees an ordinary revoke in both the switch and Attention even if refresh fails', async () => {
    const page = mountDrift({
      store: { goal_source: 'typed' },
      payload: { ...payload(), reading: regrantedBoard.response.body.reading },
      routes: {
        '/api/reading': () => json(revokeReply.response.body),
      },
    });
    await page.settle();
    page.state.routes['/api/data'] = () => json({}, 503);
    await press(screen.getByRole('switch', { name: /Allow Codex/ }));
    expect(screen.getByRole('switch', { name: /Allow Codex/ }).getAttribute('aria-checked')).toBe(
      'false',
    );
    await page.go('#n=attention');
    expect(
      screen.getByRole('region', { name: 'Unasked checks waiting for permission' }),
    ).toBeTruthy();
    expect(screen.queryByRole('region', { name: 'Unasked checks cannot run' })).toBeNull();
  });
});

const cannotRun = 'Unasked checks cannot run';
describe('A reader finding sessions a dormant grant cannot check', () => {
  it('finds each affected session once with the server explanation and no fresh grant invitation', async () => {
    const data = driftBoard({
      store: { goal_source: 'typed' },
      payload: { ...payload(), reading: dormantPolicy },
    });
    const first = data.sessions[0];
    if (!first) throw new Error('The affected session fixture is missing');
    const page = mountDrift({ hash: '#n=attention' });
    await page.settle();
    await page.poll({
      ...data,
      sessions: [first, { ...first, sid: 's2', title: 'Second affected session' }],
    });
    const cue = screen.getByRole('region', { name: cannotRun });
    expect(within(cue).getByRole('heading', { name: cannotRun })).toBeTruthy();
    expect(within(cue).getByText(dormantNote, { exact: true })).toBeTruthy();
    const links = within(cue).getAllByRole('link');
    expect(links).toHaveLength(2);
    expect(links.map((link) => link.textContent)).toEqual([first.title, 'Second affected session']);
    expect(links[0]?.getAttribute('href')).toContain('s1');
    expect(links[1]?.getAttribute('href')).toContain('s2');
    expect(cue.textContent).not.toMatch(/stopped|needs your permission|Allow Codex/);
    expect(
      screen.queryByRole('region', { name: 'Unasked checks waiting for permission' }),
    ).toBeNull();
    expect(within(cue).queryByRole('switch')).toBeNull();
    expect(readingPosts(page)).toHaveLength(0);
  });

  it.each([
    ['covered grant', policy(true), CODEX, {}, true],
    ['revoked grant', revokedPolicy, CODEX, {}, true],
    ['Claude-routed session', dormantPolicy, ROUTE, {}, true],
    ['unsupported record reader', dormantPolicy, unavailableRoute, {}, true],
    ['missing route', dormantPolicy, {}, {}, true],
    ['no typed goal', dormantPolicy, CODEX, { goal: '' }, true],
    ['adopted goal', dormantPolicy, CODEX, { goal_source: 'first-prompt' }, true],
    ['discarded goal', dormantPolicy, CODEX, { discarded_at: 1000 }, true],
    ['unasked lane off', dormantPolicy, CODEX, {}, false],
  ])(
    'does not warn the reader about a dormant Codex grant for %s',
    async (_name, reading, route, store, unasked) => {
      const page = mountDrift({
        hash: '#n=attention',
        store: { goal_source: 'typed', ...store },
        session: 'discarded_at' in store ? { annotation_discarded_at: store.discarded_at } : {},
        payload: { unasked, reading, unasked_routes: { claude: route } },
      });
      await page.settle();
      expect(screen.queryByRole('region', { name: cannotRun })).toBeNull();
      expect(screen.queryByText(dormantNote)).toBeNull();
    },
  );

  it.each([undefined, '', 37])(
    'states the missing explanation for the reader when the server note is %s',
    async (note) => {
      const page = mountDrift({
        hash: '#n=attention',
        store: { goal_source: 'typed' },
        payload: { ...payload(), reading: { ...dormantPolicy, dormant: { codex: note } } },
      });
      await page.settle();
      const cue = screen.getByRole('region', { name: cannotRun });
      expect(cue.textContent).toContain(
        'Your saved Codex permission does not cover these sessions now. The reason is not available.',
      );
      expect(cue.textContent).not.toContain('Allow Codex');
    },
  );
});

it.each([undefined, null, {}, { codex: 'unknown' }])(
  'does not tell the reader checks cannot run when words coverage is missing: %s',
  async (words) => {
    const page = mountDrift({
      hash: '#n=attention',
      store: { goal_source: 'typed' },
      payload: {
        ...payload(),
        reading: {
          ...dormantPolicy,
          words,
          rebind: {
            codex: 'What a reading sends has changed since you allowed this, so allow it again.',
          },
          dormant: {},
        },
      },
    });
    await page.settle();
    expect(screen.queryByRole('region', { name: cannotRun })).toBeNull();
    expect(
      screen.queryByRole('region', { name: 'Unasked checks waiting for permission' }),
    ).toBeNull();
  },
);

describe('A reader considering checks of ended sessions', () => {
  it.each([
    ['dormant', dormantPolicy],
    ['waiting', revokedPolicy],
  ])('is not asked to act on an ended session in the %s cue', async (_name, reading) => {
    const page = mountDrift({
      hash: '#n=attention',
      store: { goal_source: 'typed' },
      payload: { ...payload(), reading },
    });
    await page.settle();
    const data = driftBoard({
      store: { goal_source: 'typed' },
      payload: { ...payload(), reading },
    });
    const first = data.sessions[0];
    if (!first) throw new Error('The live session is missing');
    await page.poll({
      ...data,
      sessions: [
        first,
        { ...first, sid: 'ended', title: 'Ended session', ended_at: 1000, state: 'ended' },
      ],
    });
    const cue = screen.getByRole('region', {
      name:
        _name === 'dormant' ? 'Unasked checks cannot run' : 'Unasked checks waiting for permission',
    });
    expect(within(cue).getAllByRole('link')).toHaveLength(1);
    expect(within(cue).queryByRole('link', { name: 'Ended session' })).toBeNull();
    await page.poll({ ...data, sessions: [{ ...first, ended_at: 1000, state: 'ended' }] });
    expect(screen.queryByRole('region', { name: 'Unasked checks cannot run' })).toBeNull();
    expect(
      screen.queryByRole('region', { name: 'Unasked checks waiting for permission' }),
    ).toBeNull();
  });
});
