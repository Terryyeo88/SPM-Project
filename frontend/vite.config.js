import { fileURLToPath, URL } from 'node:url'

import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
// vite-plugin-vue-devtools@8.2.1 (via vite-plugin-vue-inspector@6.0.0)
// assumes a pnpm-style nested node_modules/.pnpm layout to locate its own
// Overlay.vue at dev-server start, which breaks under this project's flat
// npm install (ENOENT on a path that resolves to "/"). Disabled until
// upgraded/pinned to a version that works with npm.
// import vueDevTools from 'vite-plugin-vue-devtools'

// https://vite.dev/config/
export default defineConfig({
  plugins: [
    vue(),
  ],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    // frontend/e2e/*.spec.js are Playwright tests (npm run test:e2e), not
    // Vitest's -- they use @playwright/test's own test()/expect(), which
    // Vitest's runner can't execute (test.describe() from an async block
    // error) if its default glob sweeps them in too. Vitest and
    // Playwright both default to matching *.spec.js, so this has to be
    // excluded explicitly; it's not automatic just because the two tools
    // target different directories. Setting `exclude` replaces Vitest's
    // own default list rather than adding to it, so that default (node_
    // modules, dist, build-tool config files, etc.) is spelled out again
    // here alongside the new e2e entry.
    exclude: [
      '**/node_modules/**',
      '**/dist/**',
      '**/cypress/**',
      '**/.{idea,git,cache,output,temp}/**',
      '**/{karma,rollup,webpack,vite,vitest,jest,ava,babel,nyc,cypress,tsup,build}.config.*',
      '**/e2e/**',
    ],
  },
})
