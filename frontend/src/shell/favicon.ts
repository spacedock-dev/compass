/* The tab's own sign that the open session waits on you, for a reader on another tab (owner, 2026-10-29). Drawn
   inline as a data URI: the page ships as one file and nothing else is served for it. An icon is always set,
   because a browser keeps the last one it drew when the link is removed. */
const icon = (body: string) =>
  // The fragments below interpolate only colours from the page stylesheet.
  // nosemgrep: javascript.lang.security.html-in-template-string
  `data:image/svg+xml,${encodeURIComponent(`<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32">${body}</svg>`)}`;

export const WAITING_TITLE_PREFIX = '● Needs you · ';

export function showFavicon(doc: Document, waiting: boolean): void {
  // An SVG in a data URL has its own document and cannot inherit the board's CSS properties.
  const palette = doc.defaultView?.getComputedStyle(doc.documentElement);
  const color = palette?.getPropertyValue(waiting ? '--amber' : '--accent').trim();
  if (!color) return;
  const href = icon(
    waiting
      ? `<circle cx="16" cy="16" r="14" fill="${color}"/>`
      : `<circle cx="16" cy="16" r="11" fill="none" stroke="${color}" stroke-width="4"/>`,
  );
  let link = doc.head.querySelector<HTMLLinkElement>('link[data-next-favicon]');
  if (!link) {
    link = doc.createElement('link');
    link.rel = 'icon';
    link.type = 'image/svg+xml';
    link.setAttribute('data-next-favicon', '');
    doc.head.append(link);
  }
  if (link.getAttribute('href') !== href) link.setAttribute('href', href);
  link.setAttribute('data-waiting', String(waiting));
}
