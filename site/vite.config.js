import { defineConfig } from 'vite';
import { svelte } from '@sveltejs/vite-plugin-svelte';

// base './' so the build works from any GitHub Pages sub-path.
export default defineConfig({
  base: './',
  plugins: [svelte()],
  build: { target: 'es2020', chunkSizeWarningLimit: 300 },
});
