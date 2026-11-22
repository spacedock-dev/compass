/* A development-only page that mounts every shared control against the real backend, so a browser
   test can measure what a unit test cannot: unsaved text, caret, undo, IME composition, a native
   Base UI Select and disclosure motion across live data. It is not shipped: nothing in the production
   entry imports it, and the browser test serves it by swapping the entry inside a scratch copy of
   the tree. */
import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { ControlsProvider } from './ControlsProvider';
import { GalleryBoard } from './GalleryBoard';
import { createWorld, type Hooks, type World } from './galleryWorld';
import '../styles/tailwind.css';
import '../styles/shell.css';
import '../styles/controls.css';

export interface GalleryHandle {
  readonly runtime: World['runtime'];
  readonly gate: World['gate'];
  readonly controls: World['controls'];
  readonly hooks: Hooks;
}

/* Read from `?strict=0` so a browser test can compare StrictMode with a plain mount. */
export function mountGallery(root: HTMLElement): GalleryHandle {
  document.body.style.cssText =
    'margin:0;padding:0 1rem;background:var(--bg);color:var(--ink);font-family:system-ui,sans-serif;overflow-wrap:anywhere';
  const hooks: Hooks = { announced: [], copied: [] };
  const region = document.createElement('div');
  region.id = 'gallery-live';
  region.setAttribute('role', 'status');
  region.setAttribute('aria-live', 'polite');
  region.className = 'ctl-visually-hidden';
  root.before(region);
  const world = createWorld(hooks);
  const page = (
    <ControlsProvider controls={world.controls}>
      <div id="app">
        <GalleryBoard world={world} />
      </div>
    </ControlsProvider>
  );
  const strict = new URLSearchParams(location.search).get('strict') !== '0';
  createRoot(root).render(strict ? <StrictMode>{page}</StrictMode> : page);
  const handle: GalleryHandle = {
    runtime: world.runtime,
    gate: world.gate,
    controls: world.controls,
    hooks,
  };
  Object.assign(window, { __gallery: handle });
  return handle;
}
