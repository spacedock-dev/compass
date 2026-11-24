import type { Meta, StoryObj } from '@storybook/react-vite';
import { useEffect, useState } from 'react';
import { expect, waitFor } from 'storybook/test';
import { App } from '../src/App';
import { createRouter } from '../src/router/router';
import { fakeRouterEnvironment } from '../src/router/testing';
import { createShell } from '../src/shell/createShell';
import { createFakeClock, createFakeEnvironment } from '../src/transport/testing';
import { fakeBackend } from '../test/storage_backends';
import { contrastOf, paintedColors } from './a11y.audit';

/* An absence is plain quiet ink across the board (owner, 2026-11-24): no hatch, no dashed edge, no background.
   A board that published no session collection says so on Sessions, Needs you and a project page, and Settings
   says it is still reading, or could not read, its limits. */

function BoardWithNoSessions({ fragment }: { readonly fragment: string }) {
  const [shell] = useState(() => {
    const backend = fakeBackend();
    const clock = createFakeClock();
    return createShell({
      env: createFakeEnvironment({ clock }),
      router: createRouter(fakeRouterEnvironment(fragment).env),
      provider: () => backend,
      doc: null,
      search: '',
      reducedMotion: () => true,
      fetch: (url) =>
        Promise.resolve(
          url.startsWith('/api/data')
            ? new Response(JSON.stringify({ generated: 1_900_000_000 }))
            : new Response('{}'),
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

const meta = {
  title: 'Shell/Calm absences',
  component: BoardWithNoSessions,
  parameters: { layout: 'fullscreen' },
} satisfies Meta<typeof BoardWithNoSessions>;
export default meta;
type Story = StoryObj<typeof meta>;

const QUIET_INK = 'rgb(82, 96, 109)';

function calmAbsence(fragment: string): Story {
  return {
    args: { fragment },
    play: async ({ canvasElement }) => {
      // Read once the board has settled: an early node can be replaced by the next render.
      await waitFor(() => {
        const node = canvasElement.querySelector<HTMLElement>('.next-absence');
        if (!node?.isConnected || !node.textContent?.trim()) throw new Error('no absence drawn');
        const style = getComputedStyle(node);
        expect(style.backgroundImage).toBe('none');
        expect(style.backgroundColor).toBe('rgba(0, 0, 0, 0)');
        expect(style.borderTopStyle).toBe('none');
        expect(style.borderLeftStyle).toBe('none');
        expect(style.color).toBe(QUIET_INK);
        // Measured as plain text: 5.96:1 on the page ground, 6.46:1 on a card.
        const painted = paintedColors(node);
        if (!painted) throw new Error('the absence is not measurable');
        expect(contrastOf(painted.foreground, painted.background)).toBeGreaterThanOrEqual(5.9);
      });
    },
  };
}

export const OnSessions = calmAbsence('#n=sessions');
export const OnNeedsYou = calmAbsence('#n=attention');
export const OnSettings = calmAbsence('#n=settings');
export const OnAProjectPage = calmAbsence('#n=project:acme%2Fdashboard');
