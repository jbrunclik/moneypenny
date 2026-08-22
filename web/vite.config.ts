import { defineConfig } from 'vite';
import { resolve } from 'path';

export default defineConfig(({ command }) => ({
  root: '.',
  // Production base must match where the build lands (outDir static/assets):
  // dynamic-import chunk URLs, CSS preloads and font url()s are all
  // emitted against this base. '/static/' broke lazy chunks and fonts.
  base: command === 'build' ? '/static/assets/' : '/',
  build: {
    outDir: '../static/assets',
    emptyOutDir: true,
    manifest: true,
    rollupOptions: {
      input: resolve(__dirname, 'src/main.ts'),
      output: {
        entryFileNames: '[name]-[hash].js',
        chunkFileNames: '[name]-[hash].js',
        assetFileNames: '[name]-[hash][extname]',
        // Split the heavyweight render libraries into their own chunks:
        // their hashes stay stable across app deploys, so returning
        // clients only re-download the (small) app code
        advancedChunks: {
          groups: [
            { name: 'vendor-katex', test: /node_modules[\\/]katex[\\/]/ },
            { name: 'vendor-hljs', test: /node_modules[\\/](highlight\.js|@highlightjs)[\\/]/ },
            { name: 'vendor-markdown', test: /node_modules[\\/](marked|dompurify)[\\/]/ },
          ],
        },
      },
    },
  },
  resolve: {
    alias: {
      '@': resolve(__dirname, 'src'),
      // Zustand has React as optional peer dep - stub it out since we don't use React
      'react': resolve(__dirname, 'src/utils/react-stub.ts'),
    },
  },
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
      '/auth': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
      '/static': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
}));