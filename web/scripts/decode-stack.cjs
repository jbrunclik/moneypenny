#!/usr/bin/env node
/**
 * Decodes minified stack frames from an E2E/CI log back to source lines.
 *
 * E2E runs against the production build (minified, no sourcemaps). A
 * sourcemap build of the SAME commit produces the same chunk hashes, so its
 * maps apply exactly. Reads a log on stdin, rewrites every
 * `/static/assets/<chunk>.js:<line>:<col>` frame (WebKit `name@url` or
 * Chromium `at name (url)`) with `-> src/file.ts:line (name)` appended.
 *
 * Run with: make decode-stack < job.log   (or: node scripts/decode-stack.cjs)
 */

const { execFileSync } = require('child_process');
const fs = require('fs');
const os = require('os');
const path = require('path');
const { SourceMapConsumer } = require('source-map-js');

const WEB_DIR = path.join(__dirname, '..');
const FRAME = /\/static\/assets\/([\w.-]+\.js):(\d+):(\d+)/g;

function buildWithSourcemaps() {
  const outDir = fs.mkdtempSync(path.join(os.tmpdir(), 'decode-stack-'));
  process.stderr.write(`Building with sourcemaps into ${outDir} ...\n`);
  execFileSync('npx', ['vite', 'build', '--sourcemap', '--logLevel', 'error', '--outDir', outDir, '--emptyOutDir'], {
    cwd: WEB_DIR,
    stdio: ['ignore', 'ignore', 'inherit'],
  });
  return outDir;
}

function main() {
  const input = fs.readFileSync(0, 'utf8');
  if (!FRAME.test(input)) {
    process.stderr.write('No /static/assets/*.js:line:col frames on stdin.\n');
    process.stdout.write(input);
    return;
  }
  const outDir = buildWithSourcemaps();
  const consumers = new Map();
  const missing = new Set();
  const consumerFor = (chunk) => {
    if (!consumers.has(chunk)) {
      const mapPath = path.join(outDir, `${chunk}.map`);
      consumers.set(
        chunk,
        fs.existsSync(mapPath) ? new SourceMapConsumer(JSON.parse(fs.readFileSync(mapPath, 'utf8'))) : null
      );
    }
    return consumers.get(chunk);
  };

  const decoded = input.replace(FRAME, (frame, chunk, line, col) => {
    const consumer = consumerFor(chunk);
    if (!consumer) {
      missing.add(chunk);
      return frame;
    }
    const pos = consumer.originalPositionFor({ line: Number(line), column: Number(col) - 1 });
    if (!pos.source) return frame;
    const source = pos.source.replace(/^.*?\/web\/src\//, 'src/');
    return `${frame} -> ${source}:${pos.line}${pos.name ? ` (${pos.name})` : ''}`;
  });
  process.stdout.write(decoded);
  fs.rmSync(outDir, { recursive: true, force: true });

  if (missing.size > 0) {
    // A chunk hash that this build doesn't produce = the log came from a
    // different commit: check it out (or a worktree at it) and rerun
    process.stderr.write(
      `\nNot in this build (log from another commit?): ${[...missing].join(', ')}\n`
    );
    process.exitCode = 1;
  }
}

main();
