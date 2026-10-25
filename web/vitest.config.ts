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
      // Ratchet (T2): about 2 points under actual (Oct 25 2026: lines 46.4,
      // statements 46.2, functions 50.2, branches 42.4). Raise as coverage
      // grows; never lower to get a change through.
      thresholds: {
        lines: 44,
        statements: 44,
        functions: 48,
        branches: 40,
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
