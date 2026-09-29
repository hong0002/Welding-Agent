import { defineConfig, loadEnv } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '');
  return {
    plugins: [react()],
    // Keep hashed assets: this Windows environment crashes during recursive dist cleanup.
    // index.html is still regenerated. A clean release can use a fresh output directory.
    build: { emptyOutDir: false },
    server: {
      port: 5173,
      strictPort: true,
      proxy: { '/api': { target: process.env.VITE_API_PROXY_TARGET || env.VITE_API_PROXY_TARGET || 'http://127.0.0.1:8000' } },
    },
    preview: {
      port: 4173,
      proxy: { '/api': { target: process.env.VITE_API_PROXY_TARGET || env.VITE_API_PROXY_TARGET || 'http://127.0.0.1:8000' } },
    },
  };
});
