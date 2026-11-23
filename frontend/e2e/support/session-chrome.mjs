/* Keys name surfaces and state attributes; widths are ratios so a platform's font metrics can vary. */
export function measureSessionChrome() {
  const surfaces = {
    row: '[data-slot="card"][data-variant="session-row"]',
    current: '[data-slot="card"][data-variant="session-current"]',
    ask: '[data-slot="card"][data-variant="session-ask"]',
    landed: '[data-slot="card"][data-variant="session-landed"]',
    state: '[data-next-session-status] > [data-slot="badge"][data-variant="status"]',
    health: '[data-slot="alert"][data-variant="session-health"]',
    failure: '[data-slot="alert"][data-variant="answer-failure"]',
  };
  const rows = [];
  for (const [surface, selector] of Object.entries(surfaces)) {
    for (const el of document.querySelectorAll(selector)) {
      const css = getComputedStyle(el);
      const parent = getComputedStyle(el.parentElement);
      const parentWidth =
        el.parentElement.getBoundingClientRect().width -
        parseFloat(parent.paddingLeft) -
        parseFloat(parent.paddingRight) -
        parseFloat(parent.borderLeftWidth) -
        parseFloat(parent.borderRightWidth);
      const tone = el.closest('[data-tone]')?.getAttribute('data-tone') ?? '';
      const rowTone =
        [...el.classList].find((name) => name.startsWith('next-operation-row--')) ?? '';
      const key = `${surface}|${innerWidth <= 620 ? 'small' : innerWidth <= 1100 ? 'medium' : 'wide'}|${surface === 'current' ? tone : rowTone}`;
      const width = el.getBoundingClientRect().width;
      // A pill is content-sized: compare its excess over the actual text rather than absolute font width.
      let inlineSize = { kind: 'row', ratio: width / parentWidth };
      if (surface === 'state') {
        const range = document.createRange();
        range.selectNodeContents(el.lastChild);
        const textWidth = range.getBoundingClientRect().width;
        inlineSize = {
          kind: 'text',
          ratio: textWidth
            ? width /
              (textWidth +
                parseFloat(css.paddingLeft) +
                parseFloat(css.paddingRight) +
                parseFloat(css.borderLeftWidth) +
                parseFloat(css.borderRightWidth))
            : 0,
        };
      }
      rows.push({
        key,
        chrome: Object.fromEntries(
          [
            'color',
            'background-color',
            'border-top',
            'border-right',
            'border-bottom',
            'border-left',
            'display',
            'padding',
            'border-radius',
            'font-family',
            'font-size',
            'font-weight',
            'line-height',
          ].map((property) => [property, css.getPropertyValue(property)]),
        ),
        inlineSize,
      });
    }
  }
  for (const section of document.querySelectorAll('[data-next-delivery]')) {
    const rule = section.querySelector('[data-slot="separator"]');
    const css = getComputedStyle(rule ?? section);
    const width = (rule ?? section).getBoundingClientRect().width;
    rows.push({
      key: `delivery-rule|${innerWidth <= 620 ? 'small' : innerWidth <= 1100 ? 'medium' : 'wide'}`,
      chrome: {
        color: rule ? css.backgroundColor : css.borderTopColor,
        thickness: rule ? css.height : css.borderTopWidth,
      },
      inlineSize: {
        kind: 'row',
        ratio: width / section.parentElement.getBoundingClientRect().width,
      },
    });
  }
  return rows;
}

const currentFamilyByRecordedFamily = new Map([
  [
    '"Space Grotesk", system-ui, -apple-system, sans-serif',
    'Inter, system-ui, -apple-system, sans-serif',
  ],
  ['"IBM Plex Mono", ui-monospace, monospace', 'ui-monospace, monospace'],
]);

// The Session header adopted the sans status badge and the light palette's ink and border.
// Preserve the recorded typography size, spacing, and content sizing.
const headerStatusChrome = {
  color: 'rgb(82, 96, 109)',
  'border-top': '1px solid rgb(123, 135, 148)',
  'border-right': '1px solid rgb(123, 135, 148)',
  'border-bottom': '1px solid rgb(123, 135, 148)',
  'border-left': '1px solid rgb(123, 135, 148)',
  'font-family': 'Inter, system-ui, -apple-system, sans-serif',
  'font-weight': '500',
};

export function sessionChromeDifferences(rows, instances) {
  const differences = [];
  for (const row of rows) {
    const recorded = instances[row.key];
    const family = currentFamilyByRecordedFamily.get(recorded?.chrome['font-family']);
    let expected = family
      ? { ...recorded, chrome: { ...recorded.chrome, 'font-family': family } }
      : recorded;
    if (recorded && row.key.startsWith('state|')) {
      expected = { ...recorded, chrome: { ...recorded.chrome, ...headerStatusChrome } };
    }
    const tolerance = row.inlineSize.kind === 'text' ? 0.15 : 0.015;
    const nonFinite =
      expected &&
      (!Number.isFinite(expected.inlineSize.ratio) || !Number.isFinite(row.inlineSize.ratio));
    if (
      !expected ||
      nonFinite ||
      JSON.stringify(expected.chrome) !== JSON.stringify(row.chrome) ||
      expected.inlineSize.kind !== row.inlineSize.kind ||
      !(Math.abs(expected.inlineSize.ratio - row.inlineSize.ratio) <= tolerance)
    )
      differences.push({
        ...row,
        expected,
        reason: nonFinite
          ? `non-finite inline-size ratio: measured ${row.inlineSize.ratio}, expected ${expected.inlineSize.ratio}`
          : 'chrome or inline size changed',
      });
  }
  return differences;
}
