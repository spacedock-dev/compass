/* Surface keys deliberately exclude clocks, counts and platform-specific text widths. */
export function measureIntentChrome(native = false) {
  const nativeSurfaces = {
    'intent-note': '.next-intent-note',
    'intent-row': '.next-intent-row',
    'intent-panel': '.next-cockpit-held',
    'drift-panel': '.next-session-drift',
    'reading-job': '.next-cockpit-reading-job',
    'reading-notice': '[data-next-reading-notice]',
    'reading-stale': '.next-cockpit-result-stale',
    'drift-nudge': '.next-session-drift-nudge',
    'steer-box': '.next-cockpit-steer-box',
    'steer-receipt': '.next-steer-receipt',
    'work-panel': '.next-cockpit-work',
    'drift-pill': '.next-session-drift-pill',
    'work-flag': '.next-cockpit-work-flag',
    'draft-source': '.next-intent-draft-source',
  };
  const cards = [
    'intent-row',
    'intent-panel',
    'drift-panel',
    'reading-job',
    'reading-notice',
    'reading-stale',
    'steer-box',
    'steer-receipt',
    'work-panel',
  ];
  const badges = ['drift-pill', 'work-flag', 'draft-source'];
  const alerts = ['intent-note', 'drift-nudge'];
  const surfaces = native
    ? nativeSurfaces
    : Object.fromEntries([
        ...cards.map((name) => [name, `[data-slot="card"][data-variant="${name}"]`]),
        ...badges.map((name) => [name, `[data-slot="badge"][data-variant="${name}"]`]),
        ...alerts.map((name) => [name, `[data-slot="alert"][data-variant="${name}"]`]),
      ]);
  const rows = [];
  for (const [surface, selector] of Object.entries(surfaces)) {
    for (const el of document.querySelectorAll(selector)) {
      const css = getComputedStyle(el);
      const parent = getComputedStyle(el.parentElement);
      const width = el.getBoundingClientRect().width;
      const parentWidth =
        el.parentElement.getBoundingClientRect().width -
        parseFloat(parent.paddingLeft) -
        parseFloat(parent.paddingRight) -
        parseFloat(parent.borderLeftWidth) -
        parseFloat(parent.borderRightWidth);
      let denominator = parentWidth;
      if (!native && innerWidth > 1100) {
        if (surface === 'drift-nudge') denominator -= 32;
        if (['reading-job', 'reading-notice'].includes(surface))
          denominator = Math.min(
            parentWidth,
            33.75 * parseFloat(getComputedStyle(document.documentElement).fontSize),
          );
      }
      let inlineSize = { kind: 'row', ratio: width / denominator };
      if (['drift-pill', 'work-flag', 'draft-source'].includes(surface)) {
        const range = document.createRange();
        range.selectNodeContents(el);
        const content = range.getBoundingClientRect().width;
        inlineSize = {
          kind: 'text',
          ratio:
            width /
            (content +
              parseFloat(css.paddingLeft) +
              parseFloat(css.paddingRight) +
              parseFloat(css.borderLeftWidth) +
              parseFloat(css.borderRightWidth)),
        };
      }
      if (!el.getClientRects().length) inlineSize = { kind: 'hidden', ratio: 0 };
      const flag = el.getAttribute('data-next-entry-flag') ?? '';
      const key = `${surface}|${innerWidth <= 620 ? 'small' : innerWidth <= 1100 ? 'medium' : 'wide'}|${flag}|${inlineSize.kind}`;
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
        role: el.getAttribute('role'),
      });
    }
  }
  return rows;
}

export function intentChromeDifferences(rows, instances) {
  return rows
    .filter((row) => {
      // The notice reuses the recorded card recipe; its removed question is covered by Drift stories.
      const expected = instances[row.key.replace(/^reading-notice\|/, 'reading-consent|')];
      return (
        !expected ||
        !Number.isFinite(row.inlineSize.ratio) ||
        !Number.isFinite(expected.inlineSize.ratio) ||
        JSON.stringify(expected.chrome) !== JSON.stringify(row.chrome) ||
        expected.inlineSize.kind !== row.inlineSize.kind ||
        Math.abs(expected.inlineSize.ratio - row.inlineSize.ratio) >
          (row.inlineSize.kind === 'text' ? 0.15 : 0.015)
      );
    })
    .map((row) => ({ ...row, expected: instances[row.key] }));
}
