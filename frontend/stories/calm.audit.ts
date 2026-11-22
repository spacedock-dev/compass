import { contrastOf, isHidden, paintedControlColors } from './a11y.audit';

// At the 13 px floor this permits 0.52 px of tracking. The old .07em labels fail at every size.
const MAX_TRACKING_EM = 0.04;
const CONTROL_RATIO = 3;
const MONO_FAMILY =
  /(?:^|[\s,'"-])(?:ui-monospace|monospace|courier|menlo|monaco|consolas|[\w-]+ mono)(?:$|[\s,'"-])/i;
const RAW_TEXT = [
  ['epoch', /\b[12]\d{9}(?:\d{3})?\b/],
  [
    'hex identifier',
    /\b(?:0x[\da-f]+|[a-f]{8,64}|(?=[\da-f]*\d)(?=[\da-f]*[a-f])[\da-f]{7,64}|[\da-f]{8}(?:-[\da-f]{4}){3}-[\da-f]{12})\b/i,
  ],
  ['citation', /\[\d+\]/],
] as const;

function nodeLabel(element: Element, text: string): string {
  const tag = element.localName;
  return `${tag}${element.id ? `#${element.id}` : ''} "${text.trim().slice(0, 100)}"`;
}

function auditText(root: HTMLElement): string[] {
  const failures: string[] = [];
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  const range = document.createRange();
  for (let node = walker.nextNode(); node; node = walker.nextNode()) {
    const element = node.parentElement;
    const text = node.textContent?.trim();
    if (
      !text ||
      !element ||
      element.closest('script, style, [data-authored], [data-layer="technical"]')
    )
      continue;
    const style = getComputedStyle(element);
    let box = element;
    while (getComputedStyle(box).display === 'contents' && box.parentElement)
      box = box.parentElement;
    if (isHidden(box) || style.visibility !== 'visible') continue;
    range.selectNodeContents(node);
    if (!Array.from(range.getClientRects()).some((rect) => rect.width > 0 && rect.height > 0))
      continue;
    const label = nodeLabel(element, text);
    if (MONO_FAMILY.test(style.fontFamily))
      failures.push(`monospace (${style.fontFamily}) on ${label}`);
    if (style.textTransform.split(' ').includes('uppercase'))
      failures.push(`uppercase transform on ${label}`);
    if (
      Number.parseFloat(style.letterSpacing) >
      MAX_TRACKING_EM * Number.parseFloat(style.fontSize)
    )
      failures.push(`letter-spacing ${style.letterSpacing} on ${label}`);
    for (const [kind, pattern] of RAW_TEXT) {
      if (pattern.test(text)) failures.push(`raw ${kind} on ${label}`);
    }
  }
  return failures;
}

function auditControlBoundaries(root: HTMLElement): string[] {
  const failures: string[] = [];
  const controls = root.querySelectorAll(
    'button, a[href], input, select, textarea, summary, [role="button"], [role="checkbox"], [role="radio"], [role="switch"], [role="tab"], [role="slider"], [role="combobox"]',
  );
  for (const element of controls) {
    if (isHidden(element) || element.closest(':disabled, [aria-disabled="true"]')) continue;
    const style = getComputedStyle(element);
    const borders = new Set<string>();
    for (const side of ['top', 'bottom', 'left', 'right']) {
      const color = style.getPropertyValue(`border-${side}-color`);
      if (
        Number.parseFloat(style.getPropertyValue(`border-${side}-width`)) > 0 &&
        !/^(?:transparent|rgba\(.+, 0\))$/.test(color) &&
        style.getPropertyValue(`border-${side}-style`) !== 'hidden'
      )
        borders.add(color);
    }
    const name =
      element.getAttribute('aria-label') ||
      element.textContent?.trim() ||
      element.getAttribute('placeholder') ||
      element.id;
    for (const color of borders) {
      const colors = paintedControlColors(element, color);
      const label = nodeLabel(element, name);
      if (!colors) {
        failures.push(`cannot measure control border against the backdrop on ${label}`);
        continue;
      }
      const ratio = contrastOf(colors.foreground, colors.background);
      if (ratio < CONTROL_RATIO)
        failures.push(`control border ${ratio.toFixed(2)}:1 < ${CONTROL_RATIO}:1 on ${label}`);
    }
  }
  return failures;
}

export function auditCalm(root: HTMLElement): string[] {
  return [...auditText(root), ...auditControlBoundaries(root)];
}
