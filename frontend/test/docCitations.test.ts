import { readdirSync, readFileSync, statSync } from 'node:fs';
import { dirname, join, posix, relative, resolve } from 'node:path';
import { describe, expect, it } from 'vitest';

/* Every citation of a document heading in a frontend file (a parenthesised docs path and anchor) names a heading
   the document still has. The runtime's citations are held the same way by the Python suite; nothing held the
   frontend's until a document change stopped running the whole frontend lane, and scripts/ci_scope.py now runs this
   file for a document the frontend cites. The slugs are scripts/validate_plugins.py's `heading_slugs`, GitHub's
   rendering, ported line for line. */

const ROOT = resolve(process.cwd());
const SUFFIXES = new Set(['.py', '.ts', '.tsx', '.js', '.jsx', '.mts', '.mjs']);
const CITATION = /\(((?:\.\.\/)*docs\/[^)\s]+\.md)#([^)\s]+)\)/g;

function sources(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    if (name === 'node_modules') return [];
    if (statSync(path).isDirectory()) return sources(path);
    return SUFFIXES.has(posix.extname(name)) ? [path] : [];
  });
}

/* Frontmatter and fenced code blanked, as `markdown_prose` does: a `#` inside a fence is a comment, not a heading. */
function prose(text: string): string[] {
  const lines = text.split(/\r?\n/);
  let start = 0;
  if (lines[0]?.trim() === '---') {
    const end = lines.findIndex((line, index) => index > 0 && line.trim() === '---');
    if (end > 0) start = end + 1;
  }
  let fence: string | null = null;
  return lines.map((line, index) => {
    if (index < start) return '';
    const marker = /^\s{0,3}(`{3,}|~{3,})/.exec(line)?.[1];
    if (fence === null && marker) {
      fence = marker[0] ?? null;
      return '';
    }
    if (fence !== null) {
      if (marker && marker[0] === fence) fence = null;
      return '';
    }
    return line;
  });
}

function slugify(title: string): string {
  const rendered = title.replace(/!?\[([^\]]*)\]\([^)]*\)/g, '$1').replace(/<[^>]*>/g, '');
  return rendered
    .trim()
    .toLowerCase()
    .replace(/[^\p{L}\p{N}_\- ]/gu, '')
    .replaceAll(' ', '-');
}

function headingSlugs(markdown: string): Set<string> {
  const lines = prose(markdown);
  const slugs = new Set<string>();
  const seen = new Map<string, number>();
  lines.forEach((line, index) => {
    const atx = /^\s{0,3}#{1,6}\s+(.*?)\s*#*$/.exec(line);
    const next = lines[index + 1];
    let title: string | undefined;
    if (atx) title = atx[1];
    else if (line.trim() && next !== undefined && /^\s{0,3}(=+|-{2,})\s*$/.test(next))
      title = line.trim();
    if (title === undefined) return;
    const base = slugify(title);
    const count = seen.get(base) ?? 0;
    seen.set(base, count + 1);
    slugs.add(count === 0 ? base : `${base}-${String(count)}`);
  });
  for (const match of lines.join('\n').matchAll(/<a\s[^>]*(?:name|id)=["']([^"']+)/g)) {
    if (match[1]) slugs.add(match[1]);
  }
  return slugs;
}

describe('heading slugs', () => {
  it('slug a heading the way GitHub renders it', () => {
    expect(slugify("DEC-29: A command's result is evidence by tier")).toBe(
      'dec-29-a-commands-result-is-evidence-by-tier',
    );
    expect(slugify('Amended 2026-10-23 (owner): the [live level](x.md) comes from `Haiku`')).toBe(
      'amended-2026-10-23-owner-the-live-level-comes-from-haiku',
    );
    expect(slugify('Où <em>est</em> snake_case')).toBe('où-est-snake_case');
  });

  it('number repeats, read Setext and explicit anchors, and skip fenced code', () => {
    const markdown = [
      '# Notes',
      '## Notes',
      'Plain',
      '-----',
      '<a id="q-12"></a>',
      '```',
      '# not',
      '```',
    ].join('\n');
    expect(headingSlugs(markdown)).toEqual(new Set(['notes', 'notes-1', 'plain', 'q-12']));
  });
});

describe('frontend citations', () => {
  const citations = sources(join(ROOT, 'frontend')).flatMap((file) =>
    [...readFileSync(file, 'utf8').matchAll(CITATION)].map((match) => {
      const [, cited = '', anchor = ''] = match;
      const here = relative(ROOT, dirname(file)).split('\\').join('/');
      const document = cited.startsWith('docs/') ? cited : posix.normalize(posix.join(here, cited));
      return { file: relative(ROOT, file), document, anchor };
    }),
  );

  it('finds citations to check', () => {
    expect(citations.length).toBeGreaterThan(0);
  });

  it('resolve every one to a heading the cited document still has', () => {
    const slugs = new Map<string, Set<string>>();
    const missing = citations.filter(({ document, anchor }) => {
      if (!slugs.has(document)) {
        let text = '';
        try {
          text = readFileSync(join(ROOT, document), 'utf8');
        } catch {
          // A missing document leaves no headings, so each of its citations is reported below.
        }
        slugs.set(document, headingSlugs(text));
      }
      return !slugs.get(document)?.has(anchor);
    });
    expect(missing.map(({ file, document, anchor }) => `${file}: ${document}#${anchor}`)).toEqual(
      [],
    );
  });
});
