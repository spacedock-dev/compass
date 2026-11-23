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

const TECHNICAL = '[data-layer="technical"]';
const ACRONYMS = new Set([
  'AI',
  'AM',
  'API',
  'CLI',
  'CPU',
  'CSS',
  'GB',
  'GPU',
  'HTML',
  'HTTP',
  'HTTPS',
  'ID',
  'JSON',
  'KB',
  'MB',
  'MCP',
  'OS',
  'PDF',
  'PM',
  'PR',
  'RAM',
  'RGB',
  'SVG',
  'TCP',
  'TLS',
  'UI',
  'URL',
  'USB',
  'UTC',
  'UUID',
]);

function auditTypography(label: string, style: CSSStyleDeclaration, failures: string[]) {
  if (MONO_FAMILY.test(style.fontFamily))
    failures.push(`monospace (${style.fontFamily}) on ${label}`);
  if (style.textTransform.split(' ').includes('uppercase'))
    failures.push(`uppercase transform on ${label}`);
  if (Number.parseFloat(style.letterSpacing) > MAX_TRACKING_EM * Number.parseFloat(style.fontSize))
    failures.push(`letter-spacing ${style.letterSpacing} on ${label}`);
}

function auditWords(element: Element, text: string, failures: string[]) {
  const label = nodeLabel(element, text);
  const words = text.match(/\p{L}+/gu) ?? [];
  if (text === text.toUpperCase() && words.some((word) => word.length > 1 && !ACRONYMS.has(word)))
    failures.push(`literal all-capital label on ${label}`);
  for (const [kind, pattern] of RAW_TEXT) {
    if (pattern.test(text)) failures.push(`raw ${kind} on ${label}`);
  }
}

/* Read adjacent inline text together. A change in provenance or formatting context
   ends the run, so a payload fragment cannot complete a Compass citation. */
function auditText(root: HTMLElement): string[] {
  const failures: string[] = [];
  const walker = root.ownerDocument.createTreeWalker(
    root,
    NodeFilter.SHOW_ELEMENT | NodeFilter.SHOW_TEXT,
  );
  const range = root.ownerDocument.createRange();
  const display = (element: Element) => getComputedStyle(element).display;
  let run: { owner: Element; text: string } | undefined;
  const flush = () => {
    if (run?.text.trim()) auditWords(run.owner, run.text, failures);
    run = undefined;
  };
  for (let node = walker.nextNode(); node; node = walker.nextNode()) {
    if (node instanceof Element) {
      if (node.localName === 'br' && getComputedStyle(node).display !== 'none') flush();
      continue;
    }
    const element = node.parentElement;
    const text = node.textContent;
    if (!text || !element || element.closest('script, style')) continue;
    const style = getComputedStyle(element);
    let box = element;
    while (display(box) === 'contents' && box.parentElement) box = box.parentElement;
    if (isHidden(box) || style.visibility !== 'visible') continue;
    range.selectNodeContents(node);
    if (!Array.from(range.getClientRects()).some((rect) => rect.width > 0 && rect.height > 0))
      continue;
    if (element.closest(TECHNICAL)) {
      flush();
      continue;
    }
    if (element.closest('[data-authored]')) {
      flush();
      if (text.trim()) auditTypography(nodeLabel(element, text), style, failures);
      continue;
    }
    let owner = element;
    while (/^(?:inline|contents)$/.test(display(owner)) && owner !== root && owner.parentElement)
      owner = owner.parentElement;
    if (run?.owner !== owner) {
      flush();
      run = { owner, text: '' };
    }
    if (text.trim()) auditTypography(nodeLabel(element, text), style, failures);
    if (run) run.text += text;
  }
  flush();

  for (const field of root.querySelectorAll<HTMLInputElement | HTMLTextAreaElement>(
    'input:placeholder-shown, textarea:placeholder-shown',
  )) {
    if (!field.placeholder.trim() || field.closest(TECHNICAL) || isHidden(field)) continue;
    const style = getComputedStyle(field, '::placeholder');
    if (style.visibility !== 'visible' || Number(style.opacity) === 0) continue;
    auditTypography(nodeLabel(field, field.placeholder), style, failures);
    auditWords(field, field.placeholder, failures);
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
      const colors = paintedControlColors(element, color, 'border');
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

export function auditTechnicalMonospace(root: HTMLElement): string[] {
  return auditText(root).filter((failure) => failure.includes('monospace'));
}
