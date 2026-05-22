/// <reference types="vitest" />
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  test: {
    // Vitest's default include picks up any *.spec.ts. Walkthroughs live under
    // e2e/ and run via Playwright; keep them out of the unit-test runner.
    exclude: ['e2e/**', 'node_modules/**', 'dist/**'],
    globals: true,
    environment: 'jsdom',
    setupFiles: ['./src/setupTests.ts'],
  },
});
