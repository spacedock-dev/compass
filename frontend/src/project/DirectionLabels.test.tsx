import { fireEvent, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { scenarios } from './generate.test.helper';
import { mountProject } from './testing';

/* A direction is the reader's words, so the Course tab draws them without the harness's paste tags and never
   with an entry number in front. Claude Code wraps a paste in `<pasted_content id="N">`; a server or a
   republished history that still sends the tags must not put them, or the paste's number, in a label. */

const [, , , COURSE] = scenarios();
const WRAPPED = '\n\n<pasted_content id="7">\nShip the queue behind a flag\n</pasted_content>\n';

function rewrapped<T>(value: T): T {
  const copy = JSON.parse(JSON.stringify(value)) as T;
  const visit = (node: unknown): void => {
    if (Array.isArray(node)) node.forEach(visit);
    else if (node && typeof node === 'object') {
      const row = node as Record<string, unknown>;
      if (row['type'] === 'user_message' && typeof row['summary'] === 'string')
        row['summary'] = WRAPPED;
      Object.values(row).forEach(visit);
    }
  };
  visit(copy);
  return copy;
}

describe('a direction on the Course tab', () => {
  it('is drawn without the paste tags or an entry number, beside its episode and among the others', async () => {
    const scenario = COURSE as NonNullable<typeof COURSE>;
    const project = String((scenario.board['sessions'] as { project: string }[])[0]?.project);
    const page = mountProject({
      hash: `#n=project:${encodeURIComponent(project)}:course`,
      data: scenario.board,
      contexts: { [`${project}\n`]: rewrapped(scenario.context) },
    });
    await page.settle();
    const others = screen.queryByText(/Other directions/);
    if (others) fireEvent.click(others);
    const drawn = [
      ...document.querySelectorAll('.next-course-episode > p, .next-course-direction > p'),
    ]
      .map((node) => node.textContent ?? '')
      .filter((text) => text.includes('Ship the queue behind a flag'));
    expect(drawn.length).toBeGreaterThan(0);
    for (const text of drawn) {
      expect(text).not.toMatch(/pasted_content/);
      expect(text).not.toMatch(/#\d/);
      expect(text.replace(/^Direction · /, '')).toBe('Ship the queue behind a flag');
    }
  });
});
