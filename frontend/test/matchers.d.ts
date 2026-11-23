import 'vitest';

/* The jsdom tests register jest-dom's own matchers: setup.ts for every file, and a few files their own. Vitest's
   browser types declare the same names for browser mode, where toHaveTextContent takes no RegExp, and Vitest's
   config types load them whenever its browser provider is installed. Each entry here accepts what both
   implementations do. */
declare module 'vitest' {
  interface Assertion<R, T> {
    toBeInTheDocument(): R;
    toBeVisible(): R;
    toHaveAccessibleDescription(text?: string | RegExp | T): R;
    toHaveTextContent(
      text?: string | number | RegExp,
      options?: { readonly normalizeWhitespace: boolean },
    ): R;
  }
}
