import eslint from '@eslint/js';
import tseslint from 'typescript-eslint';

export default tseslint.config(
  eslint.configs.recommended,
  ...tseslint.configs.recommended,
  {
    ignores: ['dist/', 'node_modules/'],
  },
  {
    // Node scripts (test fixture generators)
    files: ['**/*.cjs'],
    languageOptions: {
      sourceType: 'commonjs',
      globals: { require: 'readonly', Buffer: 'readonly', __dirname: 'readonly', console: 'readonly' },
    },
    rules: { '@typescript-eslint/no-require-imports': 'off' },
  },
  {
    rules: {
      '@typescript-eslint/no-unused-vars': ['error', { argsIgnorePattern: '^_' }],
      'no-trailing-spaces': 'error',
    },
  },
  {
    // Rules from docs/conventions.md. Existing violations are recorded in
    // eslint-suppressions.json (ESLint bulk suppressions); that file only
    // shrinks - run `npx eslint src --prune-suppressions` after fixing some.
    files: ['src/**/*.ts'],
    languageOptions: {
      parserOptions: { projectService: true, tsconfigRootDir: import.meta.dirname },
    },
    rules: {
      // F4: a rejected promise nobody awaits is an unhandled rejection with no log
      '@typescript-eslint/no-floating-promises': ['error', { ignoreVoid: true }],
      '@typescript-eslint/no-misused-promises': 'error',
      '@typescript-eslint/no-non-null-assertion': 'error',
      '@typescript-eslint/no-unnecessary-type-assertion': 'error',
      // C1: function size, nesting and complexity
      'max-lines-per-function': ['error', { max: 100, skipBlankLines: true, skipComments: true }],
      'max-depth': ['error', 3],
      complexity: ['error', 15],
      // F8: log through createLogger
      'no-console': 'error',
    },
  },
  // F1: imports point down the layers (docs/conventions.md "Layers")
  {
    files: ['src/components/**/*.ts'],
    rules: {
      'no-restricted-imports': ['error', {
        patterns: [{
          group: ['**/core/*', '@/core/*'],
          message: 'Components report upward through callbacks or core/events (F1).',
        }],
      }],
    },
  },
  {
    files: ['src/utils/**/*.ts'],
    rules: {
      'no-restricted-imports': ['error', {
        patterns: [{
          group: ['**/components/*', '**/core/*', '**/state/*', '**/sync/*', '**/api/*',
            '@/components/*', '@/core/*', '@/state/*', '@/sync/*', '@/api/*'],
          message: 'utils is the bottom layer: pass what it needs in (F1).',
        }],
      }],
    },
  },
  {
    files: ['src/sync/**/*.ts'],
    rules: {
      'no-restricted-imports': ['error', {
        patterns: [{
          group: ['**/components/*', '@/components/*'],
          message: 'sync never imports UI (F1).',
        }],
      }],
    },
  },
  {
    // The logger itself, and the sandboxed artifact frame (no logger there)
    files: ['src/utils/logger.ts', 'src/artifact/**/*.ts'],
    rules: { 'no-console': 'off' },
  }
);