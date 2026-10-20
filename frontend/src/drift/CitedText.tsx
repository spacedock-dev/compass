import { Fragment, useContext, type ReactNode } from 'react';
import { DriftContext } from './context';
import { CitationLink } from './CitationLink';
import { jumpToEntry } from './jumpToEntry';

/* Compass's own sentences name entries as "#12" or "#2.1". Where the page holds and numbers the entry, the
   number is drawn as the citation link the summary uses, and presses to the row in Full activity; a number
   the page does not hold stays words. Only Compass-authored text goes through here: a model's own words keep
   every "#" they were written with. */
const CITE = /#(\d+(?:\.\d+)?)/g;

export function CitedText({ text }: { readonly text: string }): ReactNode {
  const drift = useContext(DriftContext);
  if (!drift || !text.includes('#')) return text;
  const byNumber = new Map<string, string>();
  for (const [id, n] of drift.model.numbers) if (drift.model.byId.has(id)) byNumber.set(n, id);
  const parts: ReactNode[] = [];
  let at = 0;
  for (const match of text.matchAll(CITE)) {
    const n = match[1] ?? '';
    const id = byNumber.get(n);
    if (!id) continue;
    if (match.index > at) parts.push(text.slice(at, match.index));
    parts.push(
      <CitationLink
        key={`${String(match.index)}:${n}`}
        id={id}
        aria-label={`Entry #${n}`}
        data-next-outline-entry={id}
        onJump={() => jumpToEntry(drift, id)}
      >
        {`[${n}]`}
      </CitationLink>,
    );
    at = match.index + match[0].length;
  }
  if (!parts.length) return text;
  if (at < text.length) parts.push(text.slice(at));
  return (
    <>
      {parts.map((part, index) => (
        <Fragment
          key={typeof part === 'string' ? `t${String(index)}` : (part as { key: string }).key}
        >
          {part}
        </Fragment>
      ))}
    </>
  );
}
