import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';

export function xtermIntegrity() {
  const vendor = new URL(
    '../../compass/skills/compass/compass_runtime/web/vendor/',
    import.meta.url,
  );
  const digest = (file) =>
    JSON.stringify(
      `sha384-${createHash('sha384')
        .update(readFileSync(new URL(file, vendor)))
        .digest('base64')}`,
    );
  return {
    __COMPASS_XTERM_JS_INTEGRITY__: digest('xterm.js'),
    __COMPASS_XTERM_CSS_INTEGRITY__: digest('xterm.css'),
  };
}
