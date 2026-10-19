import type { Meta, StoryObj } from '@storybook/react-vite';
import { expect, userEvent, waitFor, within } from 'storybook/test';
import { useEffect, useState } from 'react';
import { App } from '../src/App';
import { createRouter } from '../src/router/router';
import { fakeRouterEnvironment } from '../src/router/testing';
import { SAMPLE_FRAGMENT } from '../src/sample/ids';
import { TOUR } from '../src/sample/tour';
import { createShell } from '../src/shell/createShell';
import { createFakeClock, createFakeEnvironment } from '../src/transport/testing';
import { fakeBackend } from '../test/storage_backends';

/* The sample session as a new reader meets it, in real Chromium: the numbered (i) marks and their popups,
   the tinted cited entries, the held controls and the stored correction. What is asserted is hover, layout
   and colour, which the jsdom tests cannot see. The page around it polls a board of its own that has
   nothing in it, because the sample draws from its own data and never from that board. */

const meta = { title: 'Sample session/Page' } satisfies Meta;
export default meta;
type Story = StoryObj<typeof meta>;

function SampleExample({ fragment }: { readonly fragment: string }) {
  const [shell] = useState(() => {
    const history = fakeRouterEnvironment(fragment);
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
          new Response(JSON.stringify(url.startsWith('/api/data') ? { sessions: [] } : {}), {
            status: 200,
          }),
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

const marks = (root: HTMLElement) => [...root.querySelectorAll<HTMLElement>('[data-sample-mark]')];
const loaded = (root: HTMLElement) =>
  waitFor(() => expect(root.querySelectorAll('[data-next-entry-id]').length).toBeGreaterThan(10), {
    timeout: 10000,
  });

export const MarksTeachThePage: Story = {
  render: () => <SampleExample fragment={SAMPLE_FRAGMENT} />,
  play: async ({ canvasElement }) => {
    await loaded(canvasElement);
    await expect(canvasElement.querySelector('[data-sample-banner]')).toHaveTextContent(
      'Sample session (view only)',
    );
    await expect(marks(canvasElement)).toHaveLength(TOUR.length);
    // A mark draws small, but its press target reaches well past the drawn circle (a padded hit area),
    // so a point eight pixels above it still lands on it.
    const level = canvasElement.querySelector('[data-sample-mark="level"]') as HTMLElement;
    level.scrollIntoView({ block: 'center', behavior: 'instant' });
    await new Promise<void>((resolve) =>
      requestAnimationFrame(() => requestAnimationFrame(() => resolve())),
    );
    const box = level.getBoundingClientRect();
    await expect(document.elementFromPoint(box.left + box.width / 2, box.top - 8)).toBe(level);
    await userEvent.hover(level);
    const note = TOUR.find((each) => each.id === 'level');
    await waitFor(() => {
      const popup = [...document.querySelectorAll('[data-slot="popover-content"]')].find(
        (node) => node.hasAttribute('data-open') && node.textContent?.includes(note?.body ?? '?'),
      );
      expect(popup).toBeDefined();
    });
    await userEvent.unhover(level);
  },
};

/* The marks follow their parts down the one-column page, so the numbers read in order from the top: the
   tour's order is the page's. Full activity's mark sits beside its trigger, in view while it is collapsed. */
export const MarksFollowThePage: Story = {
  render: () => <SampleExample fragment={SAMPLE_FRAGMENT} />,
  play: async ({ canvasElement }) => {
    await loaded(canvasElement);
    await expect(marks(canvasElement).map((mark) => mark.getAttribute('data-sample-mark'))).toEqual(
      TOUR.map((note) => note.id),
    );
    const activity = canvasElement.querySelector('[data-sample-mark="activity"]') as HTMLElement;
    await expect(activity).toBeVisible();
    await expect(
      within(canvasElement).getByRole('button', { name: 'Full activity' }),
    ).toHaveAttribute('aria-expanded', 'false');
  },
};

export const FindingTintsItsEvidence: Story = {
  render: () => <SampleExample fragment={SAMPLE_FRAGMENT} />,
  play: async ({ canvasElement }) => {
    await loaded(canvasElement);
    await expect(canvasElement.querySelectorAll('[data-next-cited]')).toHaveLength(0);
    const jump = canvasElement.querySelector('[data-next-finding="goal"]') as HTMLElement;
    await userEvent.click(jump);
    await waitFor(() =>
      expect(canvasElement.querySelectorAll('[data-next-cited]').length).toBeGreaterThanOrEqual(2),
    );
    for (const row of canvasElement.querySelectorAll('[data-next-cited]')) {
      await expect(getComputedStyle(row).backgroundColor).not.toBe('rgba(0, 0, 0, 0)');
    }
    await expect(canvasElement.querySelector('[data-sample-held]')?.textContent ?? '').toBe('');
  },
};

export const EditsAreHeldAndSteerBackIsShown: Story = {
  render: () => <SampleExample fragment={SAMPLE_FRAGMENT} />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await loaded(canvasElement);
    await userEvent.click(
      [...canvasElement.querySelectorAll('button')].find(
        (button) => button.textContent?.trim() === 'Remove',
      ) as HTMLElement,
    );
    await expect(canvasElement.querySelector('[data-sample-held]')).toHaveTextContent(
      'View only: this sample cannot be edited, saved or run.',
    );
    await userEvent.click(
      canvasElement.querySelector('[data-next-cockpit-action="steer-back"]') as HTMLElement,
    );
    await waitFor(() => expect(canvas.getByText(/Back to my goal:/)).toBeVisible());
  },
};

export const SessionsInvitesAReader: Story = {
  render: () => <SampleExample fragment="#n=sessions" />,
  play: async ({ canvasElement }) => {
    const link = await within(canvasElement).findByRole('link', {
      name: 'See a sample session (view only)',
    });
    await expect(link).toHaveAttribute('href', SAMPLE_FRAGMENT);
  },
};
