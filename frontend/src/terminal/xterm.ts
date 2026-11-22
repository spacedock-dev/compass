/* The terminal renderer's loader. Lazy, local and offline, which is a measured packaging decision and not
   a convenience (docs/design-frontend-migration.md, "Candidate packaging"): xterm's JavaScript and CSS are
   495,775 raw bytes that every reader would otherwise pay at first open, and there is no measured startup
   benefit to bundling them. They stay vendored files the Python server hands out from `/assets/`, requested
   the first time a reader opens a terminal, and never from anywhere else. The vendored files and their
   licence are not touched here. */

declare const __COMPASS_XTERM_JS_INTEGRITY__: string;
declare const __COMPASS_XTERM_CSS_INTEGRITY__: string;

export const XTERM_JS = '/assets/xterm.js';
export const XTERM_CSS = '/assets/xterm.css';

export interface XtermOptions {
  readonly disableStdin: boolean;
  readonly cursorBlink: boolean;
  readonly minimumContrastRatio: number;
  readonly scrollback: number;
  readonly fontSize: number;
  readonly fontFamily: string;
  readonly theme: {
    readonly background: string;
    readonly foreground: string;
    readonly cursor: string;
    readonly selectionBackground: string;
    readonly selectionForeground: string;
  };
}

/* The slice of xterm this page touches. `Terminal` is a global the vendored script defines. */
export interface XtermLike {
  readonly cols: number;
  readonly rows: number;
  readonly element?: HTMLElement | undefined;
  readonly textarea?: HTMLTextAreaElement | undefined;
  readonly buffer?: { readonly active: { readonly cursorY: number } } | undefined;
  open(host: HTMLElement): void;
  write(data: string, done?: () => void): void;
  writeln(data: string): void;
  resize(cols: number, rows: number): void;
  reset(): void;
  dispose(): void;
}

export type XtermConstructor = new (options: XtermOptions) => XtermLike;

export interface XtermLoaderDeps {
  readonly document: Document;
  readonly terminal: () => XtermConstructor | undefined;
}

const STYLESHEET_FAILED = 'Console cannot open because the local terminal stylesheet did not load.';
const SCRIPT_FAILED = 'Console cannot open because the local terminal script did not load.';

export function createXtermLoader(deps: XtermLoaderDeps) {
  const { document: doc } = deps;
  let loading: Promise<XtermConstructor> | null = null;
  let sheet: Promise<void> | null = null;
  let script: Promise<void> | null = null;

  function loadSheet(): Promise<void> {
    if (sheet) return sheet;
    const link = doc.createElement('link');
    link.dataset.projectXterm = 'true';
    link.rel = 'stylesheet';
    link.href = XTERM_CSS;
    link.setAttribute('integrity', __COMPASS_XTERM_CSS_INTEGRITY__);
    link.crossOrigin = 'anonymous';
    const pending = new Promise<void>((resolve, reject) => {
      link.onload = () => resolve();
      link.onerror = () => {
        link.remove();
        reject(new Error(STYLESHEET_FAILED));
      };
      doc.head.append(link);
    });
    sheet = pending;
    pending.catch(() => {
      if (sheet === pending) sheet = null;
    });
    return pending;
  }

  function loadScript(): Promise<void> {
    if (script) return script;
    if (deps.terminal()) return Promise.resolve();
    const element = doc.createElement('script');
    element.src = XTERM_JS;
    element.setAttribute('integrity', __COMPASS_XTERM_JS_INTEGRITY__);
    element.crossOrigin = 'anonymous';
    const pending = new Promise<void>((resolve, reject) => {
      const failed = () => {
        element.remove();
        reject(new Error(SCRIPT_FAILED));
      };
      element.onload = () => {
        if (deps.terminal()) resolve();
        else failed();
      };
      element.onerror = failed;
      doc.head.append(element);
    });
    script = pending;
    pending.catch(() => {
      if (script === pending) script = null;
    });
    return pending;
  }

  return {
    /** The first call starts both requests; every later call, while it is pending or after it settled, shares them. */
    load(): Promise<XtermConstructor> {
      if (loading) return loading;
      const pending = Promise.all([loadSheet(), loadScript()]).then(() => {
        const terminal = deps.terminal();
        if (!terminal) throw new Error(SCRIPT_FAILED);
        return terminal;
      });
      loading = pending;
      pending.catch(() => {
        if (loading === pending) loading = null;
      });
      return pending;
    },
  };
}

export type XtermLoader = ReturnType<typeof createXtermLoader>;
