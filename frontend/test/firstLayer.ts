import { FIRST_LAYER_EXCEPTIONS, FIRST_LAYER_RETIREMENTS } from '../src/language/glossary';

const OUTSIDE_FIRST_LAYER = '[data-layer="technical"], [data-authored], script, style, [hidden]';
const ATTRIBUTES = ['aria-label', 'title', 'placeholder'] as const;
const INLINE =
  'abbr,b,bdi,bdo,cite,code,del,em,i,kbd,mark,q,s,samp,small,span,strong,sub,sup,time,u,var';

export function firstLayerViolations(
  root: Element,
  retired: readonly RegExp[] = FIRST_LAYER_RETIREMENTS,
  known?: (element: Element, source: string, text: string) => boolean,
) {
  const matches: string[] = [];
  const inspect = (element: Element, text: string, source: string) => {
    if (known?.(element, source, text.trim())) return;
    const words = FIRST_LAYER_EXCEPTIONS.reduce(
      (copy, exception) => copy.replace(exception, ' '),
      text,
    )
      .trim()
      .replace(/\s+/g, ' ');
    if (!retired.some((pattern) => pattern.test(words))) return;
    const location = `<${element.localName}${element.id ? ` id="${element.id}"` : ''}>`;
    matches.push(`${location} ${source} ${JSON.stringify(text.trim())}`);
  };
  const attributes = (element: Element) => {
    for (const attribute of ATTRIBUTES) {
      const value = element.getAttribute(attribute);
      if (value) inspect(element, value, attribute);
    }
  };
  const visit = (element: Element) => {
    attributes(element);
    let run = '';
    const flush = () => {
      if (run.trim()) inspect(element, run, 'text');
      run = '';
    };
    const collect = (parent: Element) => {
      for (const node of parent.childNodes) {
        if (node.nodeType === Node.TEXT_NODE) {
          run += node.textContent ?? '';
        } else if (node instanceof Element) {
          if (node.matches(OUTSIDE_FIRST_LAYER)) {
            flush();
          } else if (node.matches(INLINE) && !node.classList.contains('sr-only')) {
            attributes(node);
            collect(node);
          } else {
            flush();
            visit(node);
          }
        }
      }
    };
    collect(element);
    flush();
  };
  if (!root.closest(OUTSIDE_FIRST_LAYER)) visit(root);
  return matches;
}

/* These rendered strings were already on the layer's base. Keep the exceptions
   specific to the inherited text (or named test payload), so they cannot exempt
   new Compass labels on the same element. */
const inherited = new Set([
  '<li> text ' +
    JSON.stringify('This harness has no reading producer of its own, so Codex reads this session.'),
  '<p> text ' +
    JSON.stringify(
      'Only your messages are outlined for this harness: the outline has no agent replies, checks or files.',
    ),
  '<p> text ' +
    JSON.stringify(
      'Pi keeps no record Compass can page through, so this session has no outline. Activity log below lists what the harness reported.',
    ),
  '<p> text ' +
    JSON.stringify(
      'Compass cannot run unasked checks for this harness because it has no session record reader.',
    ),
  '<p> text ' +
    JSON.stringify(
      'This harness has no reading producer of its own. The Codex CLI was not found on this machine, and the Claude Code CLI was not found on this machine, so no analysis can run for this session.',
    ),
  '<a> aria-label ' + JSON.stringify('Open session A harness that publishes no waits'),
  '<a> aria-label ' + JSON.stringify('Open session Coordinate release [8]'),
  '<a> aria-label ' + JSON.stringify('Open session Check build [10]'),
  '<a> aria-label ' + JSON.stringify('Waiting on child "Check build [10]"'),
  '<a> aria-label ' + JSON.stringify('Child of Coordinate release [8]'),
  '<button> aria-label ' + JSON.stringify('Remove Group: "release [9]"'),
  ...['high', 'low', 'medium', 'none'].map(
    (level) => '<a> aria-label ' + JSON.stringify(`Open session drift-${level}`),
  ),
  ...['Droid', 'Claude Code'].map(
    (agent) =>
      '<li> text ' +
      JSON.stringify(
        `${agent}: Harness source could not be read; its sessions are missing here, not absent.`,
      ),
  ),
  '<p> text ' +
    JSON.stringify(
      'Read from Claude Code transcripts and Codex rollout metadata. Interactive or unknown includes unknown entrypoints and other harnesses.',
    ),
  '<p> text ' +
    JSON.stringify(
      'Recently observed is not proof the harness process is still open or closed; rows marked Ended reported their own end.',
    ),
  '<p> text ' +
    JSON.stringify(
      'Your first prompt, or your latest where the first is not published, comes from Claude Code or Codex; other harnesses show only your typed words. A goal marked from your prompt was adopted by you. Compass saves a prompt as a goal when you choose to adopt it.',
    ),
  '<span> title ' +
    JSON.stringify(
      'Compass reads this session off disk and no event from its harness can reach it, so an idle row here means nothing has changed recently rather than that the turn ended. The rest of the row was read normally.',
    ),
  '<p id="next-cockpit-reading-refused"> text ' +
    JSON.stringify('This harness sends no events, so Check progress opens only while it runs.'),
  '<li> text ' + JSON.stringify("This session's own harness reads it."),
  '<li> text ' + JSON.stringify('This session’s own harness reads it.'),
  '<p> text ' +
    JSON.stringify(
      "Answer it where the session is running. Compass cannot answer a harness's own prompt.",
    ),
  '<p> text ' +
    JSON.stringify(
      "Answer it where the session is running. Compass cannot answer a harness's own prompt. The command back into it is on",
    ),
]);

export function boardCopyViolations(root: Element) {
  return firstLayerViolations(root, FIRST_LAYER_RETIREMENTS, (element, source, text) => {
    if (
      source === 'text' &&
      (text === '[1]' || text === '[3]') &&
      element.matches('[data-next-found-cites] [data-next-cite]')
    )
      return true;
    const location = `<${element.localName}${element.id ? ` id="${element.id}"` : ''}>`;
    return inherited.has(`${location} ${source} ${JSON.stringify(text)}`);
  });
}
