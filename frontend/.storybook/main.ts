import type { StorybookConfig } from '@storybook/react-vite';
import tailwindcss from '@tailwindcss/vite';
import { fileURLToPath } from 'node:url';
import { readFonts } from '../build/package.mjs';

const config: StorybookConfig = {
  stories: ['../stories/**/*.stories.tsx'],
  framework: '@storybook/react-vite',
  addons: ['@storybook/addon-vitest'],
  core: { disableTelemetry: true, disableWhatsNewNotifications: true },
  features: { developmentModeForBuild: false },
  async previewHead(head) {
    const { css } = await readFonts(fileURLToPath(new URL('../../', import.meta.url)));
    return `${head}<style>${css}</style>`;
  },
  async viteFinal(config) {
    const { mergeConfig } = await import('vite');
    return mergeConfig(config, {
      plugins: [tailwindcss()],
      // Late optimizer discovery invalidated first-story requests with a 504. Keep its browser entries explicit.
      optimizeDeps: {
        noDiscovery: true,
        include: [
          'react',
          'react-dom',
          'react-dom/client',
          'react/jsx-runtime',
          'react/jsx-dev-runtime',
          '@base-ui/react/accordion',
          '@base-ui/react/button',
          '@base-ui/react/collapsible',
          '@base-ui/react/popover',
          '@base-ui/react/preview-card',
          '@base-ui/react/select',
          '@base-ui/react/separator',
          '@base-ui/react/tabs',
          '@base-ui/react/tooltip',
          'react-icons/pi',
          '@base-ui/react/merge-props',
          '@base-ui/react/use-render',
          'class-variance-authority',
          'clsx',
          'tailwind-merge',
          'storybook/test',
          '@storybook/react-vite > @storybook/react > @storybook/react-dom-shim',
        ],
      },
      resolve: { alias: { '@': fileURLToPath(new URL('../src', import.meta.url)) } },
      server: { host: '127.0.0.1', cors: false, strictPort: true },
    });
  },
};
export default config;
