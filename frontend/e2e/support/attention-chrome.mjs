/* Surface keys deliberately exclude clocks, counts and platform-specific text widths. */
export function measureAttentionChrome(native = false) {
  const nativeSurfaces = {
    'attention-brief': '.next-attention-brief',
    'attention-item': '.next-attention-item',
    'capacity-band': '[data-next-capacity-row]',
    'capacity-prospect': '.next-capacity-prospect',
    'quota-consent': '[data-next-usage-consent]',
    'observer-controls': '[data-next-observer-controls]',
    'observer-status': '[data-next-observer-controls] p[role=status]',
    'notify-blocked': '.next-notify-note',
  };
  const cards = [
    'attention-brief',
    'attention-item',
    'capacity-band',
    'capacity-prospect',
    'quota-consent',
    'observer-controls',
  ];
  const badges = ['notify-blocked'];
  const alerts = ['observer-status'];
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
      let parentElement = el.parentElement;
      while (getComputedStyle(parentElement).display === 'contents')
        parentElement = parentElement.parentElement;
      const parent = getComputedStyle(parentElement);
      const width = el.getBoundingClientRect().width;
      const parentWidth =
        parentElement.getBoundingClientRect().width -
        parseFloat(parent.paddingLeft) -
        parseFloat(parent.paddingRight) -
        parseFloat(parent.borderLeftWidth) -
        parseFloat(parent.borderRightWidth);
      let inlineSize = { kind: 'row', ratio: width / parentWidth };
      if (badges.includes(surface)) {
        const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
        const boxes = [];
        while (walker.nextNode()) {
          const node = walker.currentNode;
          if (node.parentElement.closest('.next-visually-hidden')) continue;
          const range = document.createRange();
          range.selectNodeContents(node);
          boxes.push(...range.getClientRects());
        }
        const content = boxes.length
          ? Math.max(...boxes.map((box) => box.right)) - Math.min(...boxes.map((box) => box.left))
          : 0;
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
      const flag = [
        el.getAttribute('data-tone') ?? '',
        el.classList.contains('next-attention-item--board') ? 'board' : '',
        el.classList.contains('next-attention-item--legacy') ? 'subject' : '',
        el.closest('.next-project-detail-rail') ? 'rail' : '',
        surface === 'notify-blocked'
          ? el.parentElement.querySelector('.next-running')
            ? 'fleet-header'
            : 'project-header'
          : '',
        surface === 'capacity-band' && el.matches(':hover') ? 'hover' : '',
      ]
        .filter(Boolean)
        .join(':');
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

export function attentionChromeDifferences(rows, instances) {
  return rows
    .filter((row) => {
      // The direct request keeps the recorded disclosure card recipe.
      const expected = instances[row.key.replace(/^observer-controls\|/, 'observer-consent|')];
      return (
        !expected ||
        expected.role !== row.role ||
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
