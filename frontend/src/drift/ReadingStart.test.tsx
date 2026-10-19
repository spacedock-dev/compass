import { act, fireEvent } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import {
  ROUTE,
  byAction,
  driftBoard,
  json,
  mountDrift,
  press,
  readingPosts,
  textOf,
} from './testing';

/* Nothing in the Drift section sends a request from a mount, a second mount under StrictMode, a poll, a
   reconnect, a route change, a hover, a focus or a keypress. The counts are requests the backend saw, by
   method and path, so a request the page forgot to mention is still counted. */
describe('Analyze starts only on a press', () => {
  it('sends no reading, cancel or correction POST from anything but a press', async () => {
    const page = mountDrift({ strict: true });
    await page.settle();
    await page.settle();
    expect(byAction('reading-ask')).not.toBeNull();
    for (const generated of [1100, 1200, 1300]) {
      await page.poll({ ...(page.state.data as object), generated });
    }
    const ask = byAction('reading-ask') as HTMLElement;
    await act(async () => {
      fireEvent.mouseOver(ask);
      fireEvent.mouseEnter(ask);
      fireEvent.focus(ask);
      fireEvent.keyDown(ask, { key: 'a' });
      fireEvent.keyDown(ask, { key: 'Enter' });
      fireEvent.keyUp(ask, { key: 'Enter' });
      fireEvent.pointerDown(ask);
    });
    await page.go('#n=intent');
    await page.go('#n=sessions');
    await page.go('#n=session:alpha%2Fapp:claude:s1');
    await page.back();
    await page.settle();
    expect(page.state.requests.filter((request) => request.method !== 'GET')).toEqual([]);
  });

  it('asks nothing of the model on a press that is refused, and says why where the press was', async () => {
    const page = mountDrift({ payload: { reading_check: 'failed' } });
    await page.settle();
    await page.settle();
    const ask = byAction('reading-ask') as HTMLElement;
    expect(ask.getAttribute('aria-disabled')).toBe('true');
    await press(ask);
    expect(readingPosts(page)).toEqual([]);
    expect(textOf('#next-cockpit-reading-refused')).toContain('not enabled in this build');
  });

  it('sends one request for one press and draws the job from the reply, however it is pressed', async () => {
    const page = mountDrift({
      routes: {
        '/api/reading': () => 'hold',
      },
    });
    await page.settle();
    await page.settle();
    const ask = byAction('reading-ask') as HTMLElement;
    await act(async () => {
      fireEvent.click(ask);
      fireEvent.click(ask);
      fireEvent.keyDown(ask, { key: 'Enter' });
      fireEvent.click(ask);
    });
    expect(readingPosts(page)).toHaveLength(1);
    const body = readingPosts(page)[0]?.body;
    expect(body).toMatchObject({
      harness: 'claude',
      sid: 's1',
      provider: 'claude',
      press: true,
      observer_model: 1,
      expected_revision: 3,
      model: 'm',
    });
    // A poll, a refresh and a route change while it is open send nothing more and retry nothing.
    await page.poll({ ...(page.state.data as object), generated: 1100 });
    await page.go('#n=sessions');
    await page.go('#n=session:alpha%2Fapp:claude:s1');
    expect(readingPosts(page)).toHaveLength(1);
    const job = { id: 'j1', phase: 'read', steps: [{ phase: 'read', text: 'Reading' }] };
    // The server publishes the job it started, so the board the refresh brings carries it.
    page.state.data = { ...(page.state.data as object), reading_jobs: { 'claude:s1': job } };
    await page.release('/api/reading', json({ ok: true, job }));
    await page.settle();
    expect(document.querySelector('[data-next-analyzing="j1"]')).not.toBeNull();
    expect(readingPosts(page)).toHaveLength(1);
  });

  it('draws the job from the reply until a board has drawn, then takes the board at its word', async () => {
    const job = { id: 'j7', phase: 'read', steps: [{ phase: 'read', text: 'Reading' }] };
    const page = mountDrift({ routes: { '/api/reading': () => json({ ok: true, job }) } });
    await page.settle();
    await page.settle();
    // The refresh the press follows with brings a board that does not hold the job, as a job that has
    // already ended would not: nothing stands over it.
    await press(byAction('reading-ask'));
    await page.settle();
    expect(document.querySelector('[data-next-analyzing]')).toBeNull();
    expect(byAction('reading-ask')).not.toBeNull();
    expect(readingPosts(page)).toHaveLength(1);
  });

  it('never retries a lost answer, and says it cannot confirm', async () => {
    const page = mountDrift({
      routes: { '/api/reading': () => new Response('not json', { status: 200 }) },
    });
    await page.settle();
    await page.settle();
    await press(byAction('reading-ask'));
    await page.settle();
    await page.advance(60_000);
    expect(readingPosts(page)).toHaveLength(1);
    expect(textOf('.next-session-drift-check')).toContain('Could not confirm the reading');
  });
});

describe('a refusal is a state', () => {
  it('stops being said the moment the reader does what it asks', async () => {
    const page = mountDrift({ payload: { reading_check: 'failed' } });
    await page.settle();
    await page.settle();
    await press(byAction('reading-ask'));
    expect(textOf('#next-cockpit-reading-refused')).toContain('not enabled in this build');
    await page.poll({ ...(page.state.data as object), generated: 1100, reading_check: 'passed' });
    expect(document.querySelector('#next-cockpit-reading-refused')).toBeNull();
    expect(textOf('.next-session-drift-check')).not.toContain('not enabled in this build');
    expect(byAction('reading-ask')?.getAttribute('aria-disabled')).toBeNull();
  });
});

describe('notices and the durable off switch', () => {
  const fresh = {
    reading: { consent: true, off: false, providers: {}, words: {}, used: 0, limit: 10 },
  };
  const notice = {
    kind: 'reading',
    provider: 'claude',
    destination: 'first.example',
    content: 4,
    tool_output: 'tools.example',
    at: 1000,
  };

  it('runs on the first press, keeps its notice through refresh and navigation, and clears it on a press without one', async () => {
    let calls = 0;
    const page = mountDrift({
      payload: fresh,
      routes: {
        '/api/reading': () => {
          calls++;
          return json(
            {
              ok: true,
              job: { id: `j${calls}`, steps: [] },
              ...(calls === 1
                ? { notice }
                : calls === 3
                  ? { notice: { ...notice, destination: 'changed.example', at: 1100 } }
                  : {}),
            },
            202,
          );
        },
      },
    });
    await page.settle();
    await page.settle();
    expect(readingPosts(page)).toHaveLength(0);
    await press(byAction('reading-ask'));
    await page.settle();
    expect(readingPosts(page)).toHaveLength(1);
    expect(readingPosts(page)[0]?.body).not.toHaveProperty('allow');
    expect(textOf('[data-next-reading-notice]')).toContain('first.example');
    expect(textOf('[data-next-reading-notice]')).toContain('Tool output goes to: tools.example');
    expect(textOf('[data-next-reading-notice]')).toContain('Your saved words.');
    expect(textOf('[data-next-reading-notice]')).toContain('Claude Code');
    expect(
      document.querySelector('[data-next-reading-notice] [data-next-cockpit-action="reading-off"]'),
    ).not.toBeNull();
    await page.go('#n=sessions');
    await page.go('#n=session:alpha%2Fapp:claude:s1');
    await page.settle();
    expect(textOf('[data-next-reading-notice]')).toContain('first.example');
    await press(byAction('reading-ask'));
    await page.settle();
    expect(document.querySelector('[data-next-reading-notice]')).toBeNull();
    await press(byAction('reading-ask'));
    await page.settle();
    expect(textOf('[data-next-reading-notice]')).toContain('changed.example');
    expect(textOf('[data-next-reading-notice]')).not.toContain('first.example');
  });

  it('names the provider the notice was recorded for after the route falls back to another', async () => {
    const page = mountDrift({
      payload: fresh,
      routes: {
        '/api/reading': () => json({ ok: true, job: { id: 'j', steps: [] }, notice }, 202),
      },
    });
    await page.settle();
    await page.settle();
    await press(byAction('reading-ask'));
    await page.settle();
    expect(textOf('[data-next-reading-notice]')).toContain('Your saved words.');
    await page.poll({
      ...(page.state.data as object),
      generated: 1200,
      reading_routes: {
        claude: {
          ...ROUTE,
          provider: 'codex',
          label: 'Codex',
          fallback: true,
          disclosure: 'This sends the session to Codex.',
          disclosure_parts: ['Codex words.'],
        },
      },
    });
    const shown = textOf('[data-next-reading-notice]');
    expect(shown).toContain('Provider: Claude Code');
    expect(shown).toContain('first.example');
    expect(shown).not.toContain('Codex');
    expect(shown).toContain("The session's words and the agent's messages.");
  });

  it('draws one Turn off readings beside a notice when no disclosure popover is drawn', async () => {
    const page = mountDrift({
      payload: { ...fresh, reading_routes: { claude: { ...ROUTE, disclosure: '' } } },
      routes: { '/api/reading': () => json({ ok: true, produced: false, notice }) },
    });
    await page.settle();
    await page.settle();
    await press(byAction('reading-ask'));
    await page.settle();
    expect(document.querySelector('[data-next-reading-notice]')).not.toBeNull();
    expect(document.querySelectorAll('[data-next-cockpit-action="reading-off"]')).toHaveLength(1);
  });

  it('leads with the cap when the cap and off both stand, since turning on cannot lift it', async () => {
    const page = mountDrift({
      payload: {
        reading: {
          consent: false,
          off: true,
          reason: 'daily-cap',
          used: 10,
          limit: 10,
          retry_at: null,
        },
      },
    });
    await page.settle();
    await page.settle();
    const lines = [
      ...document.querySelectorAll('.next-session-drift-check .next-cockpit-reading-why'),
    ]
      .map((node) => node.textContent ?? '')
      .filter((line) => /Analysis limit|Readings are off/.test(line));
    expect(lines[0]).toContain('Analysis limit reached');
    expect(lines).toContain(
      'Readings are off. Nothing is sent to a model until you turn them back on.',
    );
  });

  it('keeps the last notice while another press is pending or its response is lost', async () => {
    let first = true;
    const page = mountDrift({
      payload: fresh,
      routes: {
        '/api/reading': () => {
          if (!first) return 'hold';
          first = false;
          return json({ ok: true, job: { id: 'first', steps: [] }, notice }, 202);
        },
      },
    });
    await page.settle();
    await page.settle();
    await press(byAction('reading-ask'));
    await page.settle();
    expect(textOf('[data-next-reading-notice]')).toContain('first.example');
    await press(byAction('reading-ask'));
    expect(textOf('[data-next-reading-notice]')).toContain('first.example');
    await page.release('/api/reading', new Response('lost', { status: 200 }));
    await page.settle();
    expect(textOf('[data-next-reading-notice]')).toContain('first.example');
    expect(textOf('.next-session-drift-check')).toContain('Could not confirm the reading');
  });

  it('shows a newly published job notice after this tab had a no-notice reply', async () => {
    const page = mountDrift({
      payload: fresh,
      routes: { '/api/reading': () => json({ ok: true, produced: false }) },
    });
    await page.settle();
    await page.settle();
    await press(byAction('reading-ask'));
    await page.settle();
    expect(document.querySelector('[data-next-reading-notice]')).toBeNull();
    await page.poll({
      ...(page.state.data as object),
      generated: 1200,
      reading_jobs: { 'claude:s1': { id: 'other-tab', steps: [], notice } },
    });
    expect(textOf('[data-next-reading-notice]')).toContain('first.example');
  });

  it('restores a running job notice from the payload without sending anything', async () => {
    const page = mountDrift({
      payload: { ...fresh, reading_jobs: { 'claude:s1': { id: 'running', steps: [], notice } } },
    });
    await page.settle();
    await page.settle();
    expect(document.querySelector('[data-next-analyzing="running"]')).not.toBeNull();
    expect(textOf('[data-next-reading-notice]')).toContain('first.example');
    expect(readingPosts(page)).toHaveLength(0);
  });

  it.each([
    { consent: false, off: true, reason: '' },
    { consent: false, reason: 'readings-off' },
  ])('stays off until a turn-on press runs the reading', async (reading) => {
    const page = mountDrift({
      payload: { reading },
      routes: {
        '/api/reading': () => json({ ok: true, job: { id: 'on', steps: [] }, notice }, 202),
      },
    });
    await page.settle();
    await page.settle();
    expect(byAction('reading-ask')).toBeNull();
    expect(textOf('.next-session-drift-check')).toContain(
      'Readings are off. Nothing is sent to a model until you turn them back on.',
    );
    expect(readingPosts(page)).toHaveLength(0);
    expect(byAction('reading-on')?.textContent).toBe('Turn on readings and analyze');
    await press(byAction('reading-on'));
    await page.settle();
    expect(readingPosts(page)).toHaveLength(1);
    expect(readingPosts(page)[0]?.body).toMatchObject({
      allow: true,
      provider: 'claude',
      words_destination: 'api',
      tool_output: 'api',
      press: true,
      observer_model: 1,
    });
  });

  it.each([
    [409, 'destination-changed', 'Where this session would be sent changed'],
    [400, 'page-outdated', 'Reload this page'],
  ])('explains a refused turn-on without retrying (%s)', async (status, reason, sentence) => {
    const page = mountDrift({
      payload: { reading: { consent: false, off: true, reason: 'readings-off' } },
      routes: { '/api/reading': () => json({ ok: false, reason }, status as number) },
    });
    await page.settle();
    await page.settle();
    await press(byAction('reading-on'));
    await page.settle();
    expect(textOf('.next-session-drift-check')).toContain(sentence);
    expect(readingPosts(page)).toHaveLength(1);
  });
});

describe('a press names the session by its exact harness and sid', () => {
  it('sends the codex pair for a codex session that shares its sid with a claude one', async () => {
    const codexRoute = { ...ROUTE, provider: 'codex', harness: 'codex', model: '' };
    const payload = driftBoard();
    const claudeRow = (payload.sessions as Record<string, unknown>[])[0] as Record<string, unknown>;
    const page = mountDrift({
      hash: '#n=session:alpha%2Fapp:codex:x%3Ay',
      payload: {
        sessions: [claudeRow, { ...claudeRow, harness: 'codex', sid: 'x:y', state: 'working' }],
        reading_routes: { claude: ROUTE, codex: codexRoute },
        reading: {
          providers: { claude: true, codex: true },
          words: { claude: true, codex: true },
          tool_output: { claude: ['api'], codex: ['api'] },
          used: 0,
          limit: 10,
        },
      },
      routes: { '/api/reading': () => json({ ok: true, produced: false }) },
    });
    await page.settle();
    await page.settle();
    await press(byAction('reading-ask'));
    await page.settle();
    expect(readingPosts(page)).toHaveLength(1);
    expect(readingPosts(page)[0]?.body).toMatchObject({
      harness: 'codex',
      sid: 'x:y',
      provider: 'codex',
    });
  });
});
