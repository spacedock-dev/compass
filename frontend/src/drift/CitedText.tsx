import { Fragment, useContext, type ReactNode } from 'react';
import { DriftContext } from './context';
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
      <a
        key={`${String(match.index)}:${n}`}
        href="#"
        className="min-h-0 min-w-0 rounded-control font-[family-name:var(--mono)] text-label text-cite no-underline hover:underline focus-visible:outline-2 focus-visible:outline-solid focus-visible:outline-[var(--accent)] focus-visible:outline-offset-1"
        aria-label={`Show entry #${n} in Full activity`}
        data-next-outline-entry={id}
        onClick={(event) => {
          event.preventDefault();
          jumpToEntry(drift, id);
        }}
      >
        {`[${n}]`}
      </a>,
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
