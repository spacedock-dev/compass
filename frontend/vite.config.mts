import { xtermIntegrity } from './build/xterm-integrity.mjs';
import { fileURLToPath } from 'node:url';
import tailwindcss from '@tailwindcss/vite';
import react from '@vitejs/plugin-react';
import { defineConfig } from 'vite';

export default defineConfig({
  define: xtermIntegrity(),
  root: fileURLToPath(new URL('.', import.meta.url)),
  plugins: [react(), tailwindcss()],
  resolve: { alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) } },
  server: { host: '127.0.0.1', port: 4577, strictPort: true, cors: false },
  preview: { host: '127.0.0.1', port: 4578, strictPort: true, cors: false },
  build: {
    outDir: fileURLToPath(new URL('../.frontend-build', import.meta.url)),
    emptyOutDir: true,
  },
});
