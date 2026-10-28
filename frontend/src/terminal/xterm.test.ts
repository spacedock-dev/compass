// @vitest-environment jsdom
import { describe, expect, it } from 'vitest';
import { createXtermLoader, XTERM_CSS, XTERM_JS, type XtermConstructor } from './xterm';

class Stub {
  readonly marker = 'stub';
}
const constructorOf = (): XtermConstructor => Stub as unknown as XtermConstructor;

function setup(initial?: XtermConstructor) {
  const doc = document.implementation.createHTMLDocument('xterm');
  let terminal: XtermConstructor | undefined = initial;
  const loader = createXtermLoader({ document: doc, terminal: () => terminal });
  const link = () => doc.head.querySelector<HTMLLinkElement>('link[data-project-xterm]');
  const scripts = () => [...doc.head.querySelectorAll<HTMLScriptElement>('script')];
  return {
    doc,
    loader,
    link,
    scripts,
    provide(value: XtermConstructor | undefined) {
      terminal = value;
    },
  };
}

describe('loading the local terminal renderer', () => {
  it('adds nothing until the first terminal is opened', () => {
    const { doc } = setup();
    expect(doc.head.querySelectorAll('link, script')).toHaveLength(0);
  });

  it('asks only for the two same-origin assets, and once', async () => {
    const t = setup();
    const first = t.loader.load();
    const second = t.loader.load();
    expect(second).toBe(first);
    expect(t.link()?.getAttribute('href')).toBe(XTERM_CSS);
    expect(t.link()?.getAttribute('rel')).toBe('stylesheet');
    expect(t.scripts().map((script) => script.getAttribute('src'))).toEqual([XTERM_JS]);
    expect(XTERM_CSS).toBe('/assets/xterm.css');
    expect(XTERM_JS).toBe('/assets/xterm.js');
    t.provide(constructorOf());
    t.link()?.onload?.(new Event('load'));
    t.scripts()[0]?.onload?.(new Event('load'));
    await expect(first).resolves.toBe(Stub);
    t.loader.load();
    expect(t.scripts()).toHaveLength(1);
    expect(t.doc.head.querySelectorAll('link')).toHaveLength(1);
  });

  it('does not fetch the script again when the renderer is already on the page', async () => {
    const t = setup(constructorOf());
    const loading = t.loader.load();
    expect(t.scripts()).toHaveLength(0);
    t.link()?.onload?.(new Event('load'));
    await expect(loading).resolves.toBe(Stub);
  });

  it('rejects, and allows a later press to try again, when the stylesheet fails', async () => {
    const t = setup();
    const loading = t.loader.load();
    t.link()?.onerror?.(new Event('error'));
    await expect(loading).rejects.toThrow(
      'Console cannot open because the local terminal stylesheet did not load.',
    );
    expect(t.link()).toBeNull();
    const again = t.loader.load();
    expect(again).not.toBe(loading);
    expect(t.link()).not.toBeNull();
    again.catch(() => undefined);
  });

  it('asks for the script once even when a failed stylesheet is retried while it is still loading', async () => {
    const t = setup();
    const first = t.loader.load();
    t.link()?.onerror?.(new Event('error'));
    await expect(first).rejects.toThrow('stylesheet');
    const retry = t.loader.load();
    expect(t.scripts()).toHaveLength(1);
    t.provide(constructorOf());
    t.link()?.onload?.(new Event('load'));
    t.scripts()[0]?.onload?.(new Event('load'));
    await expect(retry).resolves.toBe(Stub);
  });

  it('rejects, and removes the script, when the script fails', async () => {
    const t = setup();
    const loading = t.loader.load();
    t.link()?.onload?.(new Event('load'));
    t.scripts()[0]?.onerror?.(new Event('error'));
    await expect(loading).rejects.toThrow(
      'Console cannot open because the local terminal script did not load.',
    );
    expect(t.scripts()).toHaveLength(0);
  });

  it('rejects when the script ran but defined no terminal', async () => {
    const t = setup();
    const loading = t.loader.load();
    t.link()?.onload?.(new Event('load'));
    t.scripts()[0]?.onload?.(new Event('load'));
    await expect(loading).rejects.toThrow(
      'Console cannot open because the local terminal script did not load.',
    );
    expect(t.scripts()).toHaveLength(0);
  });
});
