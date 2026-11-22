// @vitest-environment jsdom
import { afterEach, beforeEach, expect, it } from 'vitest';
import { showFavicon } from './favicon';

beforeEach(() => {
  document.documentElement.style.setProperty('--accent', '#2f7d5b');
  document.documentElement.style.setProperty('--amber', '#92400e');
});

afterEach(() => {
  for (const link of document.head.querySelectorAll('link[data-next-favicon]')) link.remove();
  document.documentElement.style.removeProperty('--accent');
  document.documentElement.style.removeProperty('--amber');
});

it('keeps one icon link and swaps it between resting and waiting', () => {
  showFavicon(document, false);
  const resting = document.head.querySelector('link[data-next-favicon]')?.getAttribute('href');
  showFavicon(document, true);
  const links = document.head.querySelectorAll('link[data-next-favicon]');
  expect(links).toHaveLength(1);
  expect(links[0]?.getAttribute('rel')).toBe('icon');
  expect(links[0]?.getAttribute('href')).not.toBe(resting);
  showFavicon(document, false);
  expect(links[0]?.getAttribute('href')).toBe(resting);
  expect(links[0]?.getAttribute('data-waiting')).toBe('false');
});

it.each([
  [false, 'stroke="#2f7d5b"'],
  [true, 'fill="#92400e"'],
])('draws the favicon from the page palette when waiting is %s', (waiting, paint) => {
  showFavicon(document, waiting);
  const href = document.head.querySelector('link[data-next-favicon]')?.getAttribute('href') ?? '';
  expect(href).toMatch(/^data:image\/svg\+xml,/);
  expect(decodeURIComponent(href)).toContain(paint);
});
