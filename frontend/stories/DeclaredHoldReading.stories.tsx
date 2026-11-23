import type { Meta, StoryObj } from '@storybook/react-vite';
import { expect, userEvent, waitFor, within } from 'storybook/test';
import { useEffect, useRef, useState } from 'react';
import { App } from '../src/App';
import type { PayloadData } from '../src/api/types';
import { createRouter } from '../src/router/router';
import { fakeRouterEnvironment } from '../src/router/testing';
import { createShell } from '../src/shell/createShell';
import { createFakeClock, createFakeEnvironment } from '../src/transport/testing';
import { fakeBackend } from '../test/storage_backends';
import { heldContext, heldData, heldParent, nativeData } from '../test/declaredHold';
import { openSessionTechnicalTab } from './sessionTechnical';

function Example() {
  const backend = useRef(false);
  const [shell] = useState(() =>
    createShell({
      env: createFakeEnvironment({ clock: createFakeClock() }),
      router: createRouter(fakeRouterEnvironment('#n=session:alpha-app:claude:a1b2c3d4').env),
      provider: () => fakeBackend(),
      events: { addEventListener: () => undefined, removeEventListener: () => undefined },
      search: '',
      doc: null,
      reducedMotion: () => true,
      fetch: (url) =>
        Promise.resolve(
          new Response(
            JSON.stringify(
              url.startsWith('/api/data')
                ? backend.current
                  ? heldData
                  : nativeData
                : url.startsWith('/api/project-context')
                  ? heldContext
                  : {},
            ),
            { status: 200 },
          ),
        ),
    }),
  );
  useEffect(
    () => () => {
      shell.runtime.dispose();
      shell.display.dispose();
    },
    [shell],
  );
  return (
    <>
      <button
        type="button"
        onClick={() => {
          backend.current = true;
          shell.runtime.store.acceptData(
            { ...heldData, generated: heldData.generated + 1 } as unknown as PayloadData,
            '2',
          );
          void shell.display.paint({ manual: false, accepted: true });
        }}
      >
        Apply child display hold
      </button>
      <button
        type="button"
        onClick={() =>
          shell.router.navigate({
            view: 'project',
            project: heldParent.project,
            focus: `claude:${heldParent.sid}`,
            tab: 'decisions',
          })
        }
      >
        View final result
      </button>
      <App shell={shell} />
    </>
  );
}

const meta = {
  title: 'Sessions/Declared hold preserves reading',
  component: Example,
} satisfies Meta<typeof Example>;
export default meta;
type Story = StoryObj<typeof meta>;

export const CompletedReadingAndFinalResult: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const drift = await canvas.findByRole('region', { name: 'Is it on track?' });
    const progress = within(drift);
    await expect(await progress.findByText('Out of date')).toBeVisible();
    const evidence = await openSessionTechnicalTab('Evidence', canvasElement);
    const medium = /^Medium: 1 departure/;
    await expect(await evidence.findByText(medium)).toBeVisible();
    await expect(evidence.getByText('It asked for a different change')).toBeVisible();
    const wording = drift.textContent;
    const verdict = evidence.getByText(medium).textContent;
    await expect(evidence.getByText(medium)).not.toHaveTextContent('so far');
    await userEvent.click(canvas.getByRole('button', { name: 'Apply child display hold' }));
    const childWait = await canvas.findByRole('link', { name: 'Waiting on child "Check build"' });
    await expect(childWait).toBeVisible();
    await expect(canvasElement.querySelector('[data-next-session-status]')).toBeNull();
    await expect(drift.textContent).toBe(wording);
    await expect(evidence.getByText(medium).textContent).toBe(verdict);
    await userEvent.click(canvas.getByRole('button', { name: 'View final result' }));
    const timeline = await waitFor(() => {
      const node = canvasElement.querySelector<HTMLElement>('[data-next-cockpit-semantic]');
      expect(node).not.toBeNull();
      if (!node) throw new Error('missing timeline');
      return node;
    });
    await userEvent.click(within(timeline).getByRole('button', { name: 'All events' }));
    const semantic = heldContext['semantic'] as { facts: { fact_id: string; type: string }[] };
    const result = semantic.facts.find((fact) => fact.type === 'result');
    if (!result) throw new Error('missing server result');
    await waitFor(() =>
      expect(timeline.querySelector(`[data-event-id="${result.fact_id}"]`)).toHaveTextContent(
        'The local parser checks passed.',
      ),
    );
    await expect(timeline.querySelector(`[data-event-id="${result.fact_id}"]`)).toBeVisible();
  },
};
