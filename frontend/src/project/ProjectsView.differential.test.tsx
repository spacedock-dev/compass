import { fireEvent, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { genPayload } from '../observed/generate.test.helper';
import { mountShell } from '../shell/testing';
import { genBoard, scenarios } from './generate.test.helper';
import { loadLegacyApp, parseHtml } from './legacy.test.helper';

// The redesigned list changes ranking, the group headings, row copy and nested session buttons.
// Compare the unchanged project identities and destinations across both groups after expansion.
function projectLinks(root: ParentNode, redesign: boolean) {
  return [...root.querySelectorAll(redesign ? '.project-list-item' : 'article.next-project-row')]
    .map((row) => {
      const key = row.getAttribute('data-next-project') ?? '';
      const route = redesign
        ? row.querySelector('a')?.getAttribute('href')?.slice(3)
        : row.getAttribute('data-next-route');
      return [key, route] as const;
    })
    .filter(([key]) => key !== '')
    .sort(([a], [b]) => a.localeCompare(b));
}

describe('the Projects list retains the recorded named projects and destinations', () => {
  it('agrees across generated boards and the recorded scenarios', async () => {
    const boards = Array.from({ length: 60 }, (_, index) => index + 1).map((seed) =>
      seed % 2 ? genBoard(seed) : genPayload(seed, { wellFormed: true }),
    );
    boards.push(...scenarios().map(({ board }) => board as (typeof boards)[number]));
    for (const [index, board] of boards.entries()) {
      const old = loadLegacyApp();
      old.setData(board);
      const recorded = projectLinks(parseHtml(old.call<string>('nextProjectsView', {})), false);
      const page = mountShell({ hash: '#n=projects', data: board, strict: false });
      await page.settle();
      const more = within(page.container).queryByRole('button', { name: /^Show \d+ more$/ });
      if (more) fireEvent.click(more);
      expect(projectLinks(page.container, true), `board ${String(index + 1)}`).toEqual(recorded);
      page.unmount();
    }
  }, 300_000);
});
