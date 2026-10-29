// @vitest-environment jsdom
import { afterEach, expect, it } from 'vitest';
import { RESTING_ICON, WAITING_ICON, showFavicon } from './favicon';

afterEach(() => {
  for (const link of document.head.querySelectorAll('link[data-next-favicon]')) link.remove();
});

it('keeps one icon link and swaps it between resting and waiting', () => {
  showFavicon(document, false);
  showFavicon(document, true);
  const links = document.head.querySelectorAll('link[data-next-favicon]');
  expect(links).toHaveLength(1);
  expect(links[0]?.getAttribute('rel')).toBe('icon');
  expect(links[0]?.getAttribute('href')).toBe(WAITING_ICON);
  showFavicon(document, false);
  expect(links[0]?.getAttribute('href')).toBe(RESTING_ICON);
  expect(links[0]?.getAttribute('data-waiting')).toBe('false');
});

it('draws both icons as inline SVG, so nothing else has to be served', () => {
  for (const icon of [RESTING_ICON, WAITING_ICON]) {
    expect(icon.startsWith('data:image/svg+xml,')).toBe(true);
    expect(decodeURIComponent(icon)).toContain('<svg');
  }
});
