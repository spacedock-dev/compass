/* Computed-style accessibility measurements for the stories: text contrast, horizontal overflow, clipped
   controls and visible focus. They read what Chromium computed, never a class or a token, so a restyle that
   drops a colour below the line fails here rather than in a person's eyes.

   Contrast composites each ancestor's background colour over the page's, in paint order, through a canvas so
   that `color-mix`, `oklch` and translucent colours resolve the way the browser resolves them. Text that sits on
   a gradient or an image has no single background and is reported as unmeasured, never passed. A disabled
   control is exempt, as WCAG 1.4.3 exempts inactive components, and is listed so the exemption is visible. */

export const NORMAL_RATIO = 4.5;
export const LARGE_RATIO = 3;

export interface TextMeasure {
  readonly text: string;
  readonly path: string;
  readonly ratio: number;
  readonly required: number;
  readonly foreground: string;
  readonly background: string;
}

export interface ContrastReport {
  readonly measured: TextMeasure[];
  readonly failures: TextMeasure[];
  readonly unmeasured: string[];
  readonly exempt: string[];
  readonly lowest: TextMeasure | null;
}

const canvas = document.createElement('canvas');
canvas.width = 1;
canvas.height = 1;
const paint = canvas.getContext('2d', { willReadFrequently: true }) as CanvasRenderingContext2D;

type Rgb = [number, number, number];

function over(backdrop: Rgb, color: string, alpha = 1): Rgb {
  paint.clearRect(0, 0, 1, 1);
  paint.globalAlpha = 1;
  paint.fillStyle = `rgb(${backdrop[0]} ${backdrop[1]} ${backdrop[2]})`;
  paint.fillRect(0, 0, 1, 1);
  paint.globalAlpha = alpha;
  paint.fillStyle = color;
  paint.fillRect(0, 0, 1, 1);
  const data = paint.getImageData(0, 0, 1, 1).data;
  return [data[0] ?? 0, data[1] ?? 0, data[2] ?? 0];
}

const channel = (value: number) => {
  const unit = value / 255;
  return unit <= 0.03928 ? unit / 12.92 : ((unit + 0.055) / 1.055) ** 2.4;
};
const luminance = ([r, g, b]: Rgb) =>
  0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b);
export function contrastOf(a: Rgb, b: Rgb): number {
  const [light, dark] = [luminance(a), luminance(b)].sort((x, y) => y - x) as [number, number];
  return (light + 0.05) / (dark + 0.05);
}
const hex = (rgb: Rgb) => `#${rgb.map((v) => v.toString(16).padStart(2, '0')).join('')}`;

const describe = (element: Element): string => {
  const parts: string[] = [];
  let node: Element | null = element;
  while (node && parts.length < 3 && node !== document.body) {
    const hook = [...node.getAttributeNames()].find((name) => name.startsWith('data-next'));
    parts.unshift(`${node.tagName.toLowerCase()}${hook ? `[${hook}]` : ''}`);
    node = node.parentElement;
  }
  return parts.join(' > ');
};

function isHidden(element: Element): boolean {
  const box = element.getBoundingClientRect();
  if (box.width <= 1 || box.height <= 1) return true;
  return !(element as HTMLElement).checkVisibility({
    opacityProperty: true,
    visibilityProperty: true,
    contentVisibilityAuto: true,
  });
}

/* A pulse that never ends takes an element through every opacity, so which one a snapshot catches is chance.
   The element rests at full opacity, which is what is measured. A finite fade is waited out by `settled`. */
function opacityOf(element: Element): number {
  let product = 1;
  for (let node: Element | null = element; node; node = node.parentElement) {
    const pulses = node
      .getAnimations()
      .some(
        (animation) =>
          animation.effect?.getComputedTiming().iterations === Number.POSITIVE_INFINITY,
      );
    if (!pulses) product *= Number(getComputedStyle(node).opacity);
  }
  return product;
}

export const grayOf = ([r, g, b]: Rgb, amount: number): Rgb => {
  const y = 0.2126 * r + 0.7152 * g + 0.0722 * b;
  return [r, g, b].map((v) => Math.round(v * (1 - amount) + y * amount)) as Rgb;
};

/* The colours a reader sees for an element's text and the surface behind it, or null where an image, a
   gradient or a filter other than `grayscale` sits between. A `grayscale()` ancestor turns the colours it
   draws grey, and the page backdrop outside it is not touched, so the filter is applied to the group's own
   layers only. The one level of filter the page uses is all this models. */
function resolve(
  element: Element,
  textColor?: string,
): { foreground: Rgb; background: Rgb } | null {
  const chain: Element[] = [];
  for (let node: Element | null = element; node; node = node.parentElement) chain.unshift(node);
  let backdrop: Rgb = [255, 255, 255];
  let inner: Rgb | null = null;
  let amount = 0;
  for (const node of chain) {
    const style = getComputedStyle(node);
    if (style.backgroundImage !== 'none') return null;
    if (style.filter !== 'none') {
      const match = /^grayscale\(([\d.]+)\)$/.exec(style.filter);
      if (!match || amount) return null;
      amount = Number(match[1]);
      inner = null;
    }
    const color = style.backgroundColor;
    if (color !== 'rgba(0, 0, 0, 0)' && color !== 'transparent') {
      if (amount) inner = over(inner ?? backdrop, color);
      else backdrop = over(backdrop, color);
    }
  }
  const alpha = opacityOf(element);
  const text = textColor ?? getComputedStyle(element).color;
  if (!amount) return { foreground: over(backdrop, text, alpha), background: backdrop };
  if (inner)
    return {
      foreground: grayOf(over(inner, text, alpha), amount),
      background: grayOf(inner, amount),
    };
  const swatch = over([0, 0, 0], text);
  return {
    foreground: over(backdrop, `rgb(${grayOf(swatch, amount).join(' ')})`, alpha),
    background: backdrop,
  };
}

function ownText(element: Element): string {
  return [...element.childNodes]
    .filter((node) => node.nodeType === Node.TEXT_NODE)
    .map((node) => node.textContent ?? '')
    .join('')
    .replace(/\s+/g, ' ')
    .trim();
}

function isLarge(style: CSSStyleDeclaration): boolean {
  const px = Number.parseFloat(style.fontSize);
  const bold = Number(style.fontWeight) >= 700;
  return px >= 24 || (bold && px >= 18.66);
}

/* Every element that owns visible text under `root`, measured against its computed backdrop. */
export function auditContrast(root: ParentNode): ContrastReport {
  const measured: TextMeasure[] = [];
  const unmeasured: string[] = [];
  const exempt: string[] = [];
  for (const element of root.querySelectorAll('*')) {
    if (['SCRIPT', 'STYLE', 'SVG', 'PATH'].includes(element.tagName.toUpperCase())) continue;
    if (element instanceof SVGElement && element.tagName.toLowerCase() !== 'text') continue;
    const text = ownText(element);
    if (!text || isHidden(element) || element.closest('[data-a11y-fixture]')) continue;
    const label = `${describe(element)} "${text.slice(0, 40)}"`;
    if (element.closest('[disabled], [aria-disabled="true"]')) {
      exempt.push(label);
      continue;
    }
    const style = getComputedStyle(element);
    const seen = resolve(element);
    if (!seen) {
      unmeasured.push(label);
      continue;
    }
    const { foreground, background: backdrop } = seen;
    // A glyph with no letter or digit (the live dot, a bullet) is a graphic, held to 3:1 as WCAG 1.4.11 does.
    const glyph = !/[\p{L}\p{N}]/u.test(text);
    const required = isLarge(style) || glyph ? LARGE_RATIO : NORMAL_RATIO;
    measured.push({
      text,
      path: describe(element),
      ratio: contrastOf(foreground, backdrop),
      required,
      foreground: hex(foreground),
      background: hex(backdrop),
    });
  }
  for (const field of root.querySelectorAll<HTMLInputElement | HTMLTextAreaElement>(
    'input[placeholder], textarea[placeholder]',
  )) {
    if (field.value || isHidden(field) || field.closest('[data-a11y-fixture], [disabled]'))
      continue;
    const seen = resolve(field, getComputedStyle(field, '::placeholder').color);
    if (!seen) continue;
    measured.push({
      text: field.placeholder,
      path: `${describe(field)}::placeholder`,
      ratio: contrastOf(seen.foreground, seen.background),
      required: NORMAL_RATIO,
      foreground: hex(seen.foreground),
      background: hex(seen.background),
    });
  }
  const failures = measured.filter((m) => m.ratio < m.required);
  const lowest = measured.reduce<TextMeasure | null>(
    (low, m) => (!low || m.ratio - m.required < low.ratio - low.required ? m : low),
    null,
  );
  return { measured, failures, unmeasured, exempt, lowest };
}

export const formatFailures = (report: ContrastReport): string =>
  report.failures
    .map(
      (m) =>
        `${m.ratio.toFixed(2)}:1 < ${m.required}:1 ${m.foreground} on ${m.background}  ${m.path} "${m.text.slice(0, 50)}"`,
    )
    .join('\n');

/* The page may not scroll sideways, and no control may be wider than the viewport it sits in. */
export function overflowReport(): { page: number; client: number; wide: string[] } {
  const scroller = document.scrollingElement as Element;
  const wide: string[] = [];
  for (const control of document.querySelectorAll<HTMLElement>(
    'button, a[href], input, select, textarea, [role="button"], [role="tab"], [role="switch"], [role="checkbox"], [role="radio"]',
  )) {
    if (isHidden(control)) continue;
    const box = control.getBoundingClientRect();
    if (box.right > scroller.clientWidth + 0.5 || box.left < -0.5) {
      wide.push(
        `${describe(control)} "${(control.textContent || control.getAttribute('aria-label') || '').trim().slice(0, 40)}" ${Math.round(box.left)}..${Math.round(box.right)}`,
      );
    }
  }
  return { page: scroller.scrollWidth, client: scroller.clientWidth, wide };
}

/* A control whose own label is cut off by its box: text wider than the control with overflow clipped. */
export function clippedControls(root: ParentNode): string[] {
  const clipped: string[] = [];
  for (const control of root.querySelectorAll<HTMLElement>(
    'button, a[href], [role="button"], [role="tab"], [role="switch"], input, select, textarea',
  )) {
    if (isHidden(control)) continue;
    const style = getComputedStyle(control);
    const cuts = style.overflowX !== 'visible' || style.textOverflow === 'ellipsis';
    if (cuts && control.scrollWidth > control.clientWidth + 1) clipped.push(describe(control));
  }
  return clipped;
}

export const hasFocusRing = (element: Element): boolean => {
  const style = getComputedStyle(element);
  const outline = style.outlineStyle !== 'none' && Number.parseFloat(style.outlineWidth) > 0;
  const shadow = style.boxShadow !== 'none';
  return outline || shadow;
};

/* A computed CSS colour as the sRGB triple the browser paints, on an opaque black ground. */
export const rgbOf = (color: string): Rgb => over([0, 0, 0], color);

/* Waits for the page's finite transitions and animations to land, so a colour is measured where it ends and
   not part-way through a fade. An animation that never ends (a pulse) is left running. */
export async function settled(limitMs = 2000): Promise<void> {
  const finite = document
    .getAnimations()
    .filter(
      (animation) => animation.effect?.getComputedTiming().iterations !== Number.POSITIVE_INFINITY,
    );
  await Promise.race([
    Promise.all(finite.map((animation) => animation.finished.catch(() => undefined))),
    new Promise((resolve) => setTimeout(resolve, limitMs)),
  ]);
}
