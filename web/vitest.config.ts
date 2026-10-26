import { defineConfig } from 'vitest/config';
import { resolve } from 'path';

export default defineConfig({
  test: {
    globals: true,
    environment: 'jsdom',
    include: ['tests/**/*.test.ts'],
    exclude: ['tests/e2e/**', 'tests/visual/**'],
    setupFiles: ['tests/unit/setup.ts'],
    coverage: {
      provider: 'v8',
      reporter: ['text', 'html', 'lcov'],
      include: ['src/**/*.ts'],
      exclude: ['src/types/**', 'src/utils/react-stub.ts'],
      // Ratchet (T2): about 2 points under actual (Oct 26 2026: lines 78.0,
      // statements 76.6, functions 81.1, branches 69.5). Raise as coverage
      // grows; never lower to get a change through.
      thresholds: {
        lines: 76,
        statements: 74,
        functions: 79,
        branches: 67,
      },
    },
    server: {
      deps: {
        // Tell Vitest to inline zustand so our alias works
        inline: ['zustand'],
      },
    },
  },
  resolve: {
    alias: {
      '@': resolve(__dirname, 'src'),
      // Zustand has React as optional peer dep - stub it out since we don't use React
      react: resolve(__dirname, 'src/utils/react-stub.ts'),
    },
  },
});
