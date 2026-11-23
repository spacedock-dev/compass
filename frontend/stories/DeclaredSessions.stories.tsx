import type { Meta, StoryObj } from '@storybook/react-vite';
import { expect, userEvent, waitFor, within } from 'storybook/test';
import { useEffect, useState } from 'react';
import { App } from '../src/App';
import { createRouter } from '../src/router/router';
import { fakeRouterEnvironment } from '../src/router/testing';
import { createShell } from '../src/shell/createShell';
import { createFakeClock, createFakeEnvironment } from '../src/transport/testing';
import { fakeBackend } from '../test/storage_backends';
import fixture from '../test/fixtures/declared-sessions.json';
import { projectStatusBoard } from '../test/project_boards';
import { auditCalm } from './calm.audit';

function Example({
  hash = '#n=sessions',
  childQuestion = false,
  parentQuestion = false,
  childTitle = 'Check build',
  plan = false,
  board,
}: {
  readonly hash?: string;
  readonly childQuestion?: boolean;
  readonly parentQuestion?: boolean;
  readonly childTitle?: string;
  readonly plan?: boolean;
  readonly board?: Record<string, unknown>;
}) {
  const [shell] = useState(() =>
    createShell({
      env: createFakeEnvironment({ clock: createFakeClock() }),
      router: createRouter(fakeRouterEnvironment(hash).env),
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
                ? {
                    ...fixture.payload,
                    ask: childQuestion || parentQuestion,
                    asks: childQuestion
                      ? [{ id: 'q', harness: 'codex', session_id: 'child', question: 'Continue?' }]
                      : parentQuestion
                        ? [
                            {
                              id: 'parent-q',
                              harness: 'claude',
                              session_id: 'parent',
                              question: 'Ship now?',
                            },
                          ]
                        : [],
                    sessions: [
                      ...fixture.payload.sessions.map((one) =>
                        one.sid === 'child'
                          ? {
                              ...one,
                              title: childTitle,
                              ...(plan
                                ? {
                                    spacedock: {
                                      workflows: [
                                        {
                                          workflow: 'Release',
                                          entities: [
                                            { slug: 'alpha', stage: 'build', live: true },
                                            { slug: 'beta', stage: 'plan', live: false },
                                          ],
                                        },
                                      ],
                                    },
                                  }
                                : {}),
                            }
                          : one,
                      ),
                      {
                        harness: 'codex',
                        sid: 'bare',
                        project: 'demo',
                        title: 'No label assigned',
                        state: 'idle',
                      },
                      {
                        harness: 'codex',
                        sid: 'literal',
                        project: 'demo',
                        title: 'Named label',
                        state: 'idle',
                        group: 'No group',
                      },
                      {
                        ...fixture.payload.sessions[0],
                        sid: 'second',
                        title: 'Check docs',
                        ended_at: 1899999999,
                        state: 'idle',
                      },
                    ],
                    ...board,
                  }
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
  return <App shell={shell} />;
}
const meta = { title: 'Sessions/Declared children and groups', component: Example } satisfies Meta<
  typeof Example
>;
export default meta;
type Story = StoryObj<typeof meta>;
const row = (root: HTMLElement, sid: string) =>
  root.querySelector(`[data-next-session="${sid}"]`) as HTMLElement;

export const LinkedChildrenAndWait: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await canvas.findByRole('link', { name: 'Waiting on child "Check build"' });
    const parentStatus = row(canvasElement, 'parent').querySelector('[data-next-row-state]');
    await expect(parentStatus).toHaveTextContent('Waiting on child');
    await expect(parentStatus?.querySelector('svg')).toBeNull();
    await expect(row(canvasElement, 'child')).toHaveAttribute('data-declared-depth', '1');
    const active = [
      ...canvasElement.querySelectorAll('[data-next-operation-group="active"] article'),
    ];
    await expect(active.map((node) => node.getAttribute('data-next-session'))).toEqual([
      'parent',
      'child',
    ]);
    await expect(
      within(row(canvasElement, 'child')).getByRole('link', {
        name: 'Child of Coordinate release',
      }),
    ).toBeVisible();
    await expect(row(canvasElement, 'child')).toHaveTextContent(fixture.expected.child[0] ?? '');
    await userEvent.click(canvas.getByRole('button', { name: 'Filters' }));
    await userEvent.click(canvas.getByRole('button', { name: 'More filters for power users' }));
    const popup = document.querySelector('[data-filter-facet="headless"]') as HTMLElement;
    await userEvent.click(within(popup).getByRole('checkbox', { name: /Interactive or unknown/ }));
    await userEvent.keyboard('{Escape}');
    await waitFor(() => expect(row(canvasElement, 'child')).toBeNull());
    await expect(
      canvas.getByRole('link', { name: 'Waiting on child "Check build"' }),
    ).toBeVisible();
  },
};
export const UnmatchedParentAndOwnGroup: Story = {
  play: async ({ canvasElement }) => {
    await within(canvasElement).findByText('Independent check');
    await expect(row(canvasElement, 'unlinked')).toHaveTextContent(
      'Declared parent is not on the board; not linked.',
    );
    await expect(row(canvasElement, 'unlinked')).not.toHaveAttribute('data-declared-depth');
    await expect(row(canvasElement, 'unlinked')).toHaveTextContent(
      fixture.expected.unlinked[0] ?? '',
    );
    await expect(row(canvasElement, 'unlinked').querySelectorAll('script')).toHaveLength(0);
    await expect(
      within(row(canvasElement, 'unlinked')).queryByRole('link', { name: /Child of/ }),
    ).toBeNull();
  },
};
export const GroupFilterAndGrouping: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await canvas.findByText('Independent check');
    await userEvent.click(canvas.getByRole('button', { name: 'Filters' }));
    await userEvent.click(canvas.getByRole('button', { name: 'More filters for power users' }));
    await userEvent.click(canvas.getByRole('button', { name: 'Group by group' }));
    await expect(canvas.getByRole('heading', { name: 'No group' })).toBeVisible();
    await expect(
      canvas.getAllByRole('heading', {
        name: JSON.stringify(fixture.payload.sessions[0]?.group ?? ''),
      }),
    ).toHaveLength(2);

    const popup = document.querySelector('[data-filter-facet="group"]') as HTMLElement;
    await userEvent.click(within(popup).getByRole('checkbox', { name: /release/ }));
    await userEvent.keyboard('{Escape}');
    await waitFor(() => expect(row(canvasElement, 'unlinked')).toBeNull());
    await expect(row(canvasElement, 'child')).toHaveTextContent('(from parent)');
    await expect(row(canvasElement, 'bare')).toBeNull();
    await expect(canvas.getByRole('button', { name: /Group: "release/ })).toBeVisible();
  },
};
export const ParentPageNamesChildrenAndTheirState: Story = {
  args: { hash: '#n=session:demo:claude:parent' },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const children = await canvas.findByRole('region', { name: 'Linked children' });
    await expect(children).toHaveTextContent('Check build · Working');
    await expect(children).toHaveTextContent('Check docs · Ended');
    await expect(canvasElement.querySelector('[data-next-session-status]')).toBeNull();
    await expect(
      canvas.getByRole('link', { name: 'Waiting on child "Check build"' }),
    ).toBeVisible();
  },
};
export const ChildPageNamesParent: Story = {
  args: { hash: '#n=session:demo:codex:child' },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(
      await canvas.findByRole('link', { name: 'Child of Coordinate release' }),
    ).toBeVisible();
    await expect(
      canvas.getByText((_text, node) => node?.textContent === fixture.expected.child[0]),
    ).toBeVisible();
  },
};
export const UnmatchedChildPage: Story = {
  args: { hash: '#n=session:demo:codex:unlinked' },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(
      await canvas.findByText('Declared parent is not on the board; not linked.'),
    ).toBeVisible();
    await expect(canvas.queryByRole('link', { name: /Child of/ })).toBeNull();
  },
};

export const FamilyLinksNavigateToTheirNamedSession: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const waiting = await canvas.findByRole('link', { name: 'Waiting on child "Check build"' });
    const browser =
      '__vitest_browser_runner__' in window ? (await import('vitest/browser')).page : null;
    if (browser)
      await browser.getByRole('link', { name: 'Waiting on child "Check build"' }).click();
    else await userEvent.click(waiting);
    await waitFor(() =>
      expect(canvasElement.querySelector('[data-next-session-detail]')).toHaveAttribute(
        'data-next-session-detail',
        'child',
      ),
    );
    await userEvent.click(canvas.getByRole('link', { name: 'Child of Coordinate release' }));
    await waitFor(() =>
      expect(canvasElement.querySelector('[data-next-session-detail]')).toHaveAttribute(
        'data-next-session-detail',
        'parent',
      ),
    );
  },
};

export const ParentPageKeepsAChildsExactQuestion: Story = {
  args: { hash: '#n=session:demo:claude:parent', childQuestion: true },
  play: async ({ canvasElement }) => {
    const children = await within(canvasElement).findByRole('region', { name: 'Linked children' });
    await expect(children).toHaveTextContent('Check build · Waiting on you');
  },
};

export const ParentQuestionOutranksChildWait: Story = {
  args: { parentQuestion: true },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const sessions = within(await canvas.findByRole('region', { name: 'All sessions' }));
    await expect(await sessions.findByText('Ship now?')).toBeVisible();
    const state = row(canvasElement, 'parent').querySelector('[data-next-row-state]');
    await expect(state).toHaveAccessibleName('Waiting on you');
    await expect(state).not.toHaveTextContent('Waiting on child "Check build"');
    await userEvent.click(
      within(row(canvasElement, 'parent')).getByRole('link', {
        name: 'Open session Coordinate release',
      }),
    );
    await waitFor(() =>
      expect(canvasElement.querySelector('[data-next-session-status]')).toHaveTextContent(
        'State: Waiting on you',
      ),
    );
    await expect(canvasElement.querySelector('[data-next-session-status]')).not.toHaveTextContent(
      'Waiting on child',
    );
    await expect(canvas.getAllByText('Ship now?')[0]).toBeVisible();
  },
};

function containedChild(width: number): Story {
  return {
    play: async ({ canvasElement }) => {
      const driver =
        '__vitest_browser_runner__' in window ? (await import('vitest/browser')).page : null;
      const before = { width: window.innerWidth, height: window.innerHeight };
      if (driver) await driver.viewport(width, 800);
      try {
        await within(canvasElement).findAllByRole('link', { name: 'Child of Coordinate release' });
        if (driver) await expect(window.innerWidth).toBe(width);
        const child = row(canvasElement, 'child');
        const list = child.closest('.next-operation-rows') as HTMLElement;
        const bounds = list.getBoundingClientRect();
        const parent = row(canvasElement, 'parent').getBoundingClientRect();
        const nested = child.getBoundingClientRect();
        await expect(nested.left).toBeGreaterThan(parent.left);
        await expect(nested.left).toBeGreaterThanOrEqual(bounds.left);
        await expect(nested.right).toBeLessThanOrEqual(bounds.right + 1);
      } finally {
        if (driver) await driver.viewport(before.width, before.height);
      }
    },
  };
}
export const ContainedChildAtDesktop = containedChild(1280);
export const ContainedChildAtMobile = containedChild(400);

export const LiteralNoGroupIsDistinct: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await canvas.findByText('Named label');
    await userEvent.click(canvas.getByRole('button', { name: 'Filters' }));
    await userEvent.click(canvas.getByRole('button', { name: 'More filters for power users' }));
    await userEvent.click(canvas.getByRole('button', { name: 'Group by group' }));
    await expect(canvas.getByRole('heading', { name: '"No group"' })).toBeVisible();
    await expect(canvas.getByRole('heading', { name: 'No group' })).toBeVisible();

    const popup = document.querySelector('[data-filter-facet="group"]') as HTMLElement;
    await userEvent.click(within(popup).getByRole('checkbox', { name: /^"No group"\s*1$/ }));
    await userEvent.keyboard('{Escape}');
    await waitFor(() => expect(row(canvasElement, 'bare')).toBeNull());
    await expect(row(canvasElement, 'literal')).toBeVisible();
    await expect(canvas.getByRole('button', { name: /Group: "No group"/ })).toBeVisible();
  },
};

export const GroupingRemainsVisiblyPressed: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(await canvas.findByRole('button', { name: 'Filters' }));
    await userEvent.click(canvas.getByRole('button', { name: 'More filters for power users' }));
    const toggle = canvas.getByRole('button', { name: 'Group by group' });
    const driver =
      '__vitest_browser_runner__' in window ? (await import('vitest/browser')).page : null;
    const leave = async () => {
      if (driver) await driver.getByRole('heading', { name: /^Good / }).hover();
      else await userEvent.unhover(toggle);
    };
    const colors = () => {
      const style = getComputedStyle(toggle);
      return [style.borderTopColor, style.backgroundColor, style.color];
    };
    await leave();
    const off = colors();
    await userEvent.click(toggle);
    await leave();
    await expect(toggle).toHaveAttribute('aria-pressed', 'true');
    await waitFor(() => {
      const on = colors();
      for (let i = 0; i < off.length; i++) expect(on[i]).not.toBe(off[i]);
    });
    await userEvent.click(toggle);
    await leave();
    await expect(toggle).toHaveAttribute('aria-pressed', 'false');
    await waitFor(() => expect(colors()).toEqual(off));
  },
};

export const ParentLinkFromSessionsRowUsesPointer: Story = {
  play: async ({ canvasElement }) => {
    await within(canvasElement).findByRole('link', { name: 'Open session Check build' });
    const child = row(canvasElement, 'child');
    const link = within(child).getByRole('link', { name: 'Child of Coordinate release' });
    const driver =
      '__vitest_browser_runner__' in window ? (await import('vitest/browser')).page : null;
    if (driver) await driver.elementLocator(link).click();
    else await userEvent.click(link);
    await waitFor(() =>
      expect(canvasElement.querySelector('[data-next-session-detail]')).toHaveAttribute(
        'data-next-session-detail',
        'parent',
      ),
    );
    await expect(
      within(canvasElement).getByRole('heading', { name: 'Coordinate release' }),
    ).toBeVisible();
  },
};

export const PromptFirstTitleIsAChildWait: Story = {
  args: { childTitle: 'You are verifying a fix round' },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const link = await canvas.findByRole('link', {
      name: 'Waiting on child "You are verifying a fix round"',
    });
    const state = row(canvasElement, 'parent').querySelector('[data-next-row-state]');
    await expect(state?.textContent).toBe('Waiting on child "You are verifying a fix round"');
    await expect(state).not.toHaveTextContent(/Waiting on you/i);
    await expect(link).toBeVisible();
    await userEvent.click(
      within(row(canvasElement, 'parent')).getByRole('link', {
        name: 'Open session Coordinate release',
      }),
    );
    await waitFor(() =>
      expect(canvasElement.querySelector('[data-next-session-status]')).toBeNull(),
    );
    await expect(
      canvas.getByRole('link', { name: 'Waiting on child "You are verifying a fix round"' }),
    ).toBeVisible();
  },
};

export const ProjectChildWaitAndMore: Story = {
  args: { hash: '#n=project:demo' },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const more = await canvas.findByLabelText('More');
    await expect(more).toBeVisible();
    await expect(more.querySelector('svg[data-icon="caret-down"]')).toBeVisible();
    await expect(getComputedStyle(more, '::after').content).toBe('none');
    const parent = canvasElement.querySelector('[data-next-going-on="parent"]');
    await expect(parent).toHaveTextContent('Waiting on child "Check build"');
    await expect(parent?.querySelector('[data-icon="working"]')).toBeNull();
    const scope = canvasElement.querySelector('[data-next-cockpit-scope="claude:parent"]');
    await expect(scope).toHaveTextContent('Waiting on child "Check build"');
    await expect(scope?.querySelector('[data-icon="working"]')).toBeNull();
    if (!scope) throw new Error('Expected the parent scope');
    await userEvent.click(scope);
    const focused = canvasElement.querySelector('[data-next-cockpit-viewing-session]');
    await waitFor(() =>
      expect(
        focused ?? canvasElement.querySelector('[data-next-cockpit-viewing-session]'),
      ).toHaveTextContent('Waiting on child "Check build"'),
    );
  },
};

export const ProjectsMemberAlignment: Story = {
  args: { hash: '#n=projects' },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await canvas.findByRole('button', { name: /No label assigned/ });
    const browser =
      '__vitest_browser_runner__' in window ? (await import('vitest/browser')).page : null;
    const original = { width: window.innerWidth, height: window.innerHeight };
    try {
      for (const width of [1280, 800, 400]) {
        if (browser) await browser.viewport(width, 900);
        const first = row(canvasElement, 'child');
        const unknown = row(canvasElement, 'bare');
        const harness = (element: HTMLElement) =>
          element.querySelector('.next-project-session-harness')?.getBoundingClientRect();
        const title = (element: HTMLElement) =>
          element.querySelector('.next-project-session-title')?.getBoundingClientRect();
        const icon = first.querySelector('svg[data-icon="working"]')?.getBoundingClientRect();
        await expect(icon).toBeDefined();
        await expect(icon?.right).toBeLessThanOrEqual(harness(first)?.left ?? 0);
        await expect(harness(unknown)?.left).toBe(harness(first)?.left);
        await expect(harness(unknown)?.width).toBe(harness(first)?.width);
        await expect(title(unknown)?.left).toBe(title(first)?.left);
        await expect(title(unknown)?.width).toBe(title(first)?.width);
        await expect(unknown.querySelector('svg')).toBeNull();
        await expect(unknown).toHaveTextContent('State not published');
        const chevron = canvasElement.querySelector('.next-project-chevron');
        const card = chevron?.closest('.next-project-row');
        if (!chevron || !card) throw new Error('Expected a project navigation chevron');
        const columns = getComputedStyle(card).gridTemplateColumns.split(' ');
        await expect(chevron.getBoundingClientRect().width).toBeLessThanOrEqual(
          Number.parseFloat(columns.at(-1) ?? '0'),
        );
      }
    } finally {
      if (browser) await browser.viewport(original.width, original.height);
    }
  },
};

export const ProjectsQuietRollup: Story = {
  args: { hash: '#n=projects', board: projectStatusBoard },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const scan = await canvas.findByRole('button', { name: /Scan-only session/ });
    const stopped = canvas.getByRole('button', { name: /Recorded stop/ });
    const counts = '3 sessions · 1 working · 1 quiet · 1 in no counted state';
    await expect(within(stopped).getByRole('img', { name: 'Quiet' })).toBeVisible();
    await expect(within(scan).queryByRole('img', { name: 'Quiet' })).toBeNull();
    await expect(
      within(scan).getByText('Read by scanning: no turn end can be observed here'),
    ).toBeVisible();
    await expect(canvas.getByText(counts)).toBeVisible();
    await userEvent.click(canvas.getByText('rollup', { selector: 'strong' }));
    await expect(await canvas.findByText(counts, { selector: 'p' })).toBeVisible();
  },
};

export const AttentionQuietCoverage: Story = {
  args: { hash: '#n=attention', board: projectStatusBoard },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(
      await canvas.findByText(
        '0 waiting on you · 0 worth a look · 0 ready to wrap up. 1 with limited state evidence.',
      ),
    ).toBeVisible();
    await expect(canvas.getByRole('status', { name: 'Working sessions' })).toHaveTextContent(
      '1 session working',
    );
    await expect(canvas.queryByRole('heading', { name: /^Ready to wrap up/ })).toBeNull();
  },
};

export const ProjectDisplayedStateRollup: Story = {
  args: {
    hash: '#n=projects',
    board: {
      ...fixture.payload,
      ask: true,
      asks: [{ id: 'q', harness: 'claude', session_id: 'stopped', question: 'Review the result?' }],
      sessions: [
        ...fixture.payload.sessions,
        {
          sid: 'stopped',
          title: 'Review the result',
          project: 'demo',
          harness: 'claude',
          state: 'idle',
          finished_at: fixture.payload.generated - 10,
        },
      ],
    },
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const counts = '4 sessions · 1 working · 1 waiting on you · 2 in no counted state';
    const checkParent = async (parent: HTMLElement) => {
      await expect(within(parent).getByText('Waiting on child "Check build"')).toBeVisible();
      await expect(within(parent).queryByRole('img')).toBeNull();
    };
    const request = await canvas.findByRole('button', { name: /Review the result/ });
    await expect(within(request).getByRole('img', { name: 'Waiting on you' })).toBeVisible();
    await checkParent(row(canvasElement, 'parent'));
    await expect(canvas.getByText(counts)).toBeVisible();
    await userEvent.click(canvas.getByText('demo', { selector: 'strong' }));
    await expect(await canvas.findByText(counts, { selector: 'p' })).toBeVisible();
    const parent = canvasElement.querySelector<HTMLElement>('[data-next-going-on="parent"]');
    if (!parent) throw new Error('Expected the parent activity row');
    await checkParent(parent);
  },
};

export const PlanEntityStatus: Story = {
  args: { hash: '#n=project:demo', plan: true },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(await canvas.findByRole('button', { name: 'Show project plan' }));
    for (const [slug, state] of [
      ['alpha', 'Live'],
      ['beta', 'Pending'],
    ]) {
      const entity = canvasElement.querySelector(`[data-next-plan-entity="${slug}"]`);
      await waitFor(() => expect(entity).toBeVisible());
      await expect(entity).toHaveTextContent(state ?? '');
      await expect(entity?.querySelector('svg')).toHaveAttribute('aria-hidden', 'true');
    }
  },
};

export const PublishedGroupAndRelationshipNames: Story = {
  args: {
    board: {
      sessions: fixture.payload.sessions.map((one) => {
        if (one.sid === 'parent')
          return { ...one, title: 'Coordinate release [8]', group: 'release [9]' };
        if (one.sid === 'child') return { ...one, title: 'Check build [10]', group: 'release [9]' };
        return one;
      }),
    },
  },
  play: async ({ canvas, canvasElement }) => {
    const parent = await canvas.findByRole('link', { name: 'Child of Coordinate release [8]' });
    await expect(parent).toBeVisible();
    await expect(
      canvas.getByRole('link', { name: 'Waiting on child "Check build [10]"' }),
    ).toBeVisible();
    await userEvent.click(canvas.getByRole('button', { name: 'Filters' }));
    await userEvent.click(canvas.getByRole('button', { name: 'More filters for power users' }));
    await userEvent.click(canvas.getByRole('button', { name: 'Group by group' }));
    await expect(canvas.getAllByRole('heading', { name: '"release [9]"' })[0]).toBeVisible();
    const group = canvas.getByRole('checkbox', { name: /^"release \[9\]"/ });
    await waitFor(() => expect(auditCalm(canvasElement)).toEqual([]));
    await userEvent.click(group);
    await expect(
      canvas.getByRole('button', { name: /Remove Group: "release \[9\]"/ }),
    ).toBeVisible();
    await waitFor(() => expect(auditCalm(canvasElement)).toEqual([]));

    const currentParent = canvas.getByRole('link', { name: 'Child of Coordinate release [8]' });
    const prefix = currentParent.firstChild;
    if (!(prefix instanceof Text)) throw new Error('The relationship has no Compass prefix');
    const words = prefix.data;
    prefix.data = 'Child of [12] ';
    try {
      await expect(currentParent).toHaveTextContent('Child of [12] Coordinate release [8]');
      await expect(auditCalm(canvasElement)).toContainEqual(
        expect.stringMatching(/citation.*Child of \[12\]/),
      );
    } finally {
      prefix.data = words;
    }
  },
};
