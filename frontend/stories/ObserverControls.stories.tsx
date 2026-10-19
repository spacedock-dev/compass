import type { Meta, StoryObj } from '@storybook/react-vite';
import { expect, userEvent, within } from 'storybook/test';
import { useEffect, useState } from 'react';
import { ObserverControls } from '../src/capacity/ObserverControls';
import { createShell } from '../src/shell/createShell';
import { ShellContext } from '../src/shell/context';
import { createFakeClock, createFakeEnvironment } from '../src/transport/testing';
import { fakeBackend } from '../test/storage_backends';

const focus = { harness: 'claude', sid: 's1' };
const disclosure =
  'Redacted transcript excerpts and workflow stage go through Codex for a goal summary.';
const requests: string[] = [];
function GoalExample() {
  const [shell] = useState(() => {
    requests.length = 0;
    let summaries = 0;
    const json = (body: unknown) => new Response(JSON.stringify(body), { status: 200 });
    return createShell({
      env: createFakeEnvironment({ clock: createFakeClock() }),
      provider: () => fakeBackend(),
      events: { addEventListener: () => undefined, removeEventListener: () => undefined },
      search: '',
      doc: null,
      reducedMotion: () => true,
      fetch: async (url, init) => {
        if (url.startsWith('/api/data'))
          return json({ generated: 1, sessions: [], reading: { consent: true, off: false } });
        if (url === '/api/reading') {
          requests.push(String(init?.body));
          return json({ ok: true, reading: { consent: false, off: true, reason: 'readings-off' } });
        }
        const requested = url.includes('observer_model=1');
        if (requested) {
          summaries++;
          requests.push(url);
        }
        return json({
          observer_model: {
            enabled: true,
            disclosure,
            ...(requested && summaries === 1
              ? {
                  notice: {
                    kind: 'goal',
                    provider: 'codex',
                    destination: 'goal.example',
                    tool_output: '',
                    content: 4,
                    at: 1000,
                  },
                }
              : {}),
          },
        });
      },
    });
  });
  useEffect(() => {
    const release = shell.runtime.acquire();
    void shell.runtime
      .refresh()
      .then(() => shell.runtime.loadContext({ projectKey: 'demo', focus }));
    return () => {
      release();
      shell.runtime.dispose();
      shell.display.dispose();
    };
  }, [shell]);
  return (
    <ShellContext.Provider value={shell}>
      <ObserverControls projectKey="demo" focus={focus} />
    </ShellContext.Provider>
  );
}
const meta = { title: 'Capacity/Goal summary notice', component: GoalExample } satisfies Meta<
  typeof GoalExample
>;
export default meta;
type Story = StoryObj<typeof meta>;
export const DirectRequestAndOnePressOff: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const summarize = await canvas.findByRole('button', { name: 'Summarize this session' });
    await expect(requests).toHaveLength(0);
    await userEvent.click(summarize);
    await expect(await canvas.findByText('Words go to: goal.example')).toBeVisible();
    await expect(requests).toHaveLength(1);
    await userEvent.click(canvas.getByRole('button', { name: 'Turn off readings' }));
    await expect(
      await canvas.findByText(
        'Readings are off. Nothing is sent to a model until you turn them back on.',
      ),
    ).toBeVisible();
    await expect(canvas.queryByRole('button', { name: 'Summarize this session' })).toBeNull();
    await expect(JSON.parse(requests[1] ?? '{}')).toEqual({
      consent: 'off',
      press: true,
      observer_model: 1,
    });
  },
};
