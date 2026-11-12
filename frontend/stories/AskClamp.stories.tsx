import type { Meta, StoryObj } from '@storybook/react-vite';
import { expect, waitFor } from 'storybook/test';
import { useEffect, useState } from 'react';
import { App } from '../src/App';
import { createRouter } from '../src/router/router';
import { fakeRouterEnvironment } from '../src/router/testing';
import { createShell } from '../src/shell/createShell';
import { createFakeClock, createFakeEnvironment } from '../src/transport/testing';
import { fakeBackend } from '../test/storage_backends';

/* A held question can run to 2,000 characters. The compact places that show it, the Sessions row and the
   project's waiting rail, show its opening in three lines; the session page's answer block shows all of it.
   The whole text stays in the DOM, so a screen reader still reads every word. */

const meta = { title: 'Sessions/Long question clamp' } satisfies Meta;
export default meta;
type Story = StoryObj<typeof meta>;

const G = 1900000000;
const WORDS = 'Should the synthetic migration run against the staging copy first ';
const QUESTION = `${WORDS.repeat(40).slice(0, 1_999).trimEnd()}…`;

function Board({ hash }: { readonly hash: string }) {
  const [shell] = useState(() => {
    const history = fakeRouterEnvironment(hash);
    const json = (body: unknown) => new Response(JSON.stringify(body), { status: 200 });
    return createShell({
      env: createFakeEnvironment({ clock: createFakeClock() }),
      router: createRouter(history.env),
      provider: () => fakeBackend(),
      events: { addEventListener: () => undefined, removeEventListener: () => undefined },
      search: '',
      doc: null,
      reducedMotion: () => true,
      fetch: (url) =>
        Promise.resolve(
          url.startsWith('/api/data')
            ? json({
                generated: G,
                harnesses: [
                  { key: 'claude', label: 'Claude Code', reports_rate: true, discovered: true },
                ],
                ask: true,
                asks: [
                  {
                    id: 'q1',
                    session_id: 's1',
                    harness: 'claude',
                    question: QUESTION,
                    options: ['Yes, run it', 'Not yet'],
                    age_sec: 30,
                    question_sent_chars: 2_500,
                    dropped_options: 0,
                  },
                ],
                sessions: [
                  {
                    harness: 'claude',
                    sid: 's1',
                    project: 'demo',
                    project_key: '/demo',
                    title: 'Synthetic clamp session',
                    state: 'needs_input',
                    started_at: G - 3600,
                    blocked_since: G - 300,
                  },
                ],
              })
            : json({}),
        ),
    });
  });
  useEffect(
    () => () => {
      shell.runtime.dispose();
      shell.display.dispose();
    },
    [shell],
  );
  return <App shell={shell} />;
}

async function atWidth(width: number, check: () => Promise<void>) {
  const browserPage =
    '__vitest_browser_runner__' in window ? (await import('vitest/browser')).page : null;
  const before = { width: window.innerWidth, height: window.innerHeight };
  if (browserPage) await browserPage.viewport(width, 800);
  try {
    if (browserPage) await expect(window.innerWidth).toBe(width);
    await check();
  } finally {
    if (browserPage) await browserPage.viewport(before.width, before.height);
  }
}

/* Clamped: the whole question is in the element, and it draws no taller than three of its lines. */
async function clampedToThreeLines(find: () => HTMLElement | null) {
  const element = await waitFor(() => {
    const found = find();
    expect(found).not.toBeNull();
    return found as HTMLElement;
  });
  await expect(element.textContent).toBe(QUESTION);
  const style = getComputedStyle(element);
  await expect(style.webkitLineClamp).toBe('3');
  const line = Number.parseFloat(style.lineHeight);
  await expect(element.getBoundingClientRect().height).toBeLessThanOrEqual(line * 3 + 1);
  await expect(element.scrollHeight).toBeGreaterThan(element.clientHeight);
}

export const SessionsRow: Story = {
  render: () => <Board hash="#n=sessions" />,
  play: async ({ canvasElement }) => {
    for (const width of [1280, 400]) {
      await atWidth(width, () =>
        clampedToThreeLines(() =>
          canvasElement.querySelector<HTMLElement>('[data-next-operation-fact="blocked"] em'),
        ),
      );
    }
  },
};

export const WaitingRail: Story = {
  render: () => <Board hash="#n=project:demo:console" />,
  play: async ({ canvasElement }) => {
    for (const width of [1280, 400]) {
      await atWidth(width, () =>
        clampedToThreeLines(() => canvasElement.querySelector<HTMLElement>('.next-rail-question')),
      );
    }
  },
};
