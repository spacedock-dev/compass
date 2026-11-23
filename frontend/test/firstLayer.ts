import { FIRST_LAYER_EXCEPTIONS, FIRST_LAYER_RETIREMENTS } from '../src/language/glossary';

const OUTSIDE_FIRST_LAYER = '[data-layer="technical"], [data-authored], script, style';
const ATTRIBUTES = ['aria-label', 'title', 'placeholder'] as const;

export function firstLayerViolations(
  root: Element,
  retired: readonly RegExp[] = FIRST_LAYER_RETIREMENTS,
) {
  const matches: string[] = [];
  for (const element of [root, ...root.querySelectorAll('*')]) {
    if (element.closest(OUTSIDE_FIRST_LAYER)) continue;
    const location = `<${element.localName}${element.id ? ` id="${element.id}"` : ''}>`;
    const inspect = (text: string, source: string) => {
      const words = FIRST_LAYER_EXCEPTIONS.reduce(
        (copy, exception) => copy.replace(exception, ' '),
        text,
      ).trim();
      if (retired.some((pattern) => pattern.test(words)))
        matches.push(`${location} ${source} ${JSON.stringify(text.trim())}`);
    };
    for (const attribute of ATTRIBUTES) {
      const value = element.getAttribute(attribute);
      if (value) inspect(value, attribute);
    }
    for (const node of element.childNodes) {
      if (node.nodeType === Node.TEXT_NODE && node.textContent?.trim())
        inspect(node.textContent, 'text');
    }
  }
  return matches;
}
