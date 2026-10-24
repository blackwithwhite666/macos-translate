import { defineConfig } from 'vite';
import { viteSingleFile } from 'vite-plugin-singlefile';

// Один минифицированный index.html — он целиком эмбедится в MacOSTranslate.app
export default defineConfig({
  plugins: [viteSingleFile()],
  build: {
    outDir: 'dist',
  },
  server: {
    // dev-режим: проксируем API на gateway
    proxy: {
      '/ws': { target: 'ws://127.0.0.1:8765', ws: true },
    },
  },
});
