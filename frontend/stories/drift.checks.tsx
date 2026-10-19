import { flushSync } from 'react-dom';
import { createRoot } from 'react-dom/client';
import {
  PiCheck,
  PiCheckBold,
  PiCheckCircle,
  PiCheckFat,
  PiChecks,
  PiCheckSquare,
} from 'react-icons/pi';
import { expect } from 'storybook/test';

/* The checks every Drift story holds a result to, shared by the stage stories and the drift card stories. Not a
   story file, so Storybook lists nothing from it. */

/* A result's account of the work is never "done": no word for it and no mark. The mark is drawn by CSS on an
   empty span, so the words alone cannot show it: every pseudo-element's generated content is read, and no
   icon of the page's check family may sit in the result. */
const CHECK_GLYPHS = /[\u221a\u2611\u2705\u2713\u2714\u{10102}\u{1f5f8}\u{1f5f9}\u{1fbb1}]/u;

function checkIconPaths(): Set<string> {
  const host = document.createElement('div');
  const root = createRoot(host);
  const icons = [PiCheck, PiCheckBold, PiCheckCircle, PiCheckFat, PiChecks, PiCheckSquare];
  flushSync(() =>
    root.render(
      <>
        {icons.map((Glyph, index) => (
          <Glyph key={index} />
        ))}
      </>,
    ),
  );
  const paths = new Set(
    [...host.querySelectorAll('path')].map((path) => path.getAttribute('d') ?? ''),
  );
  root.unmount();
  paths.delete('');
  return paths;
}

export async function noCheckMark(root: HTMLElement) {
  await expect(root.textContent).not.toMatch(CHECK_GLYPHS);
  const generated = [root, ...root.querySelectorAll<HTMLElement>('*')].flatMap((node) =>
    (['::before', '::after'] as const).map((pseudo) => getComputedStyle(node, pseudo).content),
  );
  await expect(generated.filter((content) => CHECK_GLYPHS.test(content))).toEqual([]);
  const checks = checkIconPaths();
  await expect(checks.size).toBeGreaterThan(0);
  const drawnChecks = [...root.querySelectorAll('svg path')].filter((path) =>
    checks.has(path.getAttribute('d') ?? ''),
  );
  await expect(drawnChecks).toEqual([]);
}

export async function neverDone(root: HTMLElement) {
  await expect(root.textContent).not.toMatch(/\bDone\b/);
  await noCheckMark(root);
}
