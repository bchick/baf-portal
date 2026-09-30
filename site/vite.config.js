import { defineConfig } from 'vite';
import { svelte } from '@sveltejs/vite-plugin-svelte';

// base './' so the build works from any GitHub Pages sub-path.
// The bundle includes the 3D bead models (~70 KB gzip); the real budget is
// 150 KB gzip for the initial load, so warn on raw size above 400 KB.
export default defineConfig({
  base: './',
  plugins: [svelte()],
  build: { target: 'es2020', chunkSizeWarningLimit: 400 },
});
