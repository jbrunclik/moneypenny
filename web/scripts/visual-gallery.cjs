#!/usr/bin/env node
/**
 * Generates an HTML gallery of visual test baseline screenshots.
 * Run with: node scripts/visual-gallery.js
 * Output: web/visual-gallery.html
 */

const fs = require('fs');
const path = require('path');

const VISUAL_TEST_DIR = path.join(__dirname, '..', 'tests', 'visual');
const OUTPUT_FILE = path.join(__dirname, '..', 'visual-gallery.html');

// Find all snapshot directories
const snapshotDirs = fs.readdirSync(VISUAL_TEST_DIR)
  .filter(f => f.endsWith('-snapshots') && fs.statSync(path.join(VISUAL_TEST_DIR, f)).isDirectory());

// Collect all screenshots
const screenshots = [];
for (const dir of snapshotDirs) {
  const testFile = dir.replace('-snapshots', '');
  const dirPath = path.join(VISUAL_TEST_DIR, dir);
  const files = fs.readdirSync(dirPath)
    .filter(f => f.endsWith('.png'))
    .sort();

  for (const file of files) {
    const filePath = path.join(dirPath, file);
    const stats = fs.statSync(filePath);

    // Parse filename: name-browser-platform.png
    const parts = file.replace('.png', '').split('-');
    const platform = parts.pop();
    const browser = parts.pop();
    const name = parts.join('-');

    screenshots.push({
      testFile,
      name,
      browser,
      platform,
      file,
      path: `tests/visual/${dir}/${file}`,
      size: (stats.size / 1024).toFixed(1) + ' KB',
      modified: stats.mtime.toISOString().split('T')[0],
    });
  }
}

// Group by test file and name
const grouped = {};
for (const s of screenshots) {
  const key = `${s.testFile}/${s.name}`;
  if (!grouped[key]) {
    grouped[key] = {
      testFile: s.testFile,
      name: s.name,
      variants: [],
    };
  }
  grouped[key].variants.push(s);
}

// Generate HTML
const html = `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Visual Test Gallery</title>
  <style>
    * { box-sizing: border-box; }
    body {
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
      margin: 0;
      padding: 20px;
      background: #1a1a2e;
      color: #eee;
    }
    h1 {
      margin: 0 0 20px;
      color: #fff;
    }
    .stats {
      color: #888;
      margin-bottom: 30px;
    }
    .filter-bar {
      display: flex;
      gap: 10px;
      margin-bottom: 20px;
      flex-wrap: wrap;
    }
    .filter-bar input, .filter-bar select {
      padding: 8px 12px;
      border: 1px solid #333;
      border-radius: 6px;
      background: #16213e;
      color: #eee;
      font-size: 14px;
    }
    .filter-bar input { flex: 1; min-width: 200px; }
    .test-group {
      margin-bottom: 40px;
      background: #16213e;
      border-radius: 12px;
      padding: 20px;
    }
    .test-group h2 {
      margin: 0 0 15px;
      font-size: 18px;
      color: #a78bfa;
    }
    .screenshot-row {
      margin-bottom: 30px;
    }
    .screenshot-row h3 {
      margin: 0 0 10px;
      font-size: 14px;
      color: #888;
    }
    .variants {
      display: flex;
      gap: 20px;
      flex-wrap: wrap;
    }
    .variant {
      background: #0f0f23;
      border-radius: 8px;
      overflow: hidden;
      max-width: 600px;
    }
    .variant img {
      display: block;
      max-width: 100%;
      height: auto;
      cursor: zoom-in;
    }
    .variant-info {
      padding: 10px;
      font-size: 12px;
      color: #888;
      display: flex;
      gap: 15px;
    }
    .variant-info span {
      display: flex;
      align-items: center;
      gap: 4px;
    }
    .badge {
      background: #333;
      padding: 2px 8px;
      border-radius: 4px;
      font-size: 11px;
    }
    .badge.chromium { background: #4285f4; color: #fff; }
    .badge.webkit { background: #6e6e6e; color: #fff; }
    .badge.firefox { background: #ff7139; color: #fff; }

    /* Lightbox */
    .lightbox {
      display: none;
      position: fixed;
      top: 0;
      left: 0;
      right: 0;
      bottom: 0;
      background: rgba(0,0,0,0.95);
      z-index: 1000;
      justify-content: center;
      align-items: center;
      cursor: zoom-out;
    }
    .lightbox.open { display: flex; }
    .lightbox img {
      max-width: 95vw;
      max-height: 95vh;
      object-fit: contain;
    }

    /* Hidden by filter */
    .hidden { display: none !important; }
  </style>
</head>
<body>
  <h1>Visual Test Gallery</h1>
  <p class="stats">${screenshots.length} screenshots across ${snapshotDirs.length} test files</p>

  <div class="filter-bar">
    <input type="text" id="search" placeholder="Filter by name..." />
    <select id="browser-filter">
      <option value="">All browsers</option>
      <option value="chromium">Chromium</option>
      <option value="webkit">WebKit</option>
      <option value="firefox">Firefox</option>
    </select>
    <select id="test-filter">
      <option value="">All test files</option>
      ${[...new Set(screenshots.map(s => s.testFile))].map(t => `<option value="${t}">${t}</option>`).join('')}
    </select>
  </div>

  ${Object.values(grouped).map(group => `
    <div class="test-group" data-test="${group.testFile}">
      <h2>${group.testFile}</h2>
      <div class="screenshot-row" data-name="${group.name}">
        <h3>${group.name}</h3>
        <div class="variants">
          ${group.variants.map(v => `
            <div class="variant" data-browser="${v.browser}">
              <img src="${v.path}" alt="${v.name}" loading="lazy" onclick="openLightbox(this.src)" />
              <div class="variant-info">
                <span class="badge ${v.browser}">${v.browser}</span>
                <span>${v.platform}</span>
                <span>${v.size}</span>
                <span>${v.modified}</span>
              </div>
            </div>
          `).join('')}
        </div>
      </div>
    </div>
  `).join('')}

  <div class="lightbox" id="lightbox" onclick="closeLightbox()">
    <img id="lightbox-img" src="" alt="" />
  </div>

  <script>
    // Filter functionality
    const search = document.getElementById('search');
    const browserFilter = document.getElementById('browser-filter');
    const testFilter = document.getElementById('test-filter');

    function applyFilters() {
      const searchTerm = search.value.toLowerCase();
      const browser = browserFilter.value;
      const test = testFilter.value;

      document.querySelectorAll('.test-group').forEach(group => {
        if (test && group.dataset.test !== test) {
          group.classList.add('hidden');
          return;
        }
        group.classList.remove('hidden');

        group.querySelectorAll('.screenshot-row').forEach(row => {
          const name = row.dataset.name.toLowerCase();
          if (searchTerm && !name.includes(searchTerm)) {
            row.classList.add('hidden');
            return;
          }
          row.classList.remove('hidden');

          row.querySelectorAll('.variant').forEach(variant => {
            if (browser && variant.dataset.browser !== browser) {
              variant.classList.add('hidden');
            } else {
              variant.classList.remove('hidden');
            }
          });
        });
      });
    }

    search.addEventListener('input', applyFilters);
    browserFilter.addEventListener('change', applyFilters);
    testFilter.addEventListener('change', applyFilters);

    // Lightbox
    function openLightbox(src) {
      document.getElementById('lightbox-img').src = src;
      document.getElementById('lightbox').classList.add('open');
    }

    function closeLightbox() {
      document.getElementById('lightbox').classList.remove('open');
    }

    document.addEventListener('keydown', e => {
      if (e.key === 'Escape') closeLightbox();
    });
  </script>
</body>
</html>
`;

fs.writeFileSync(OUTPUT_FILE, html);
console.log(`Generated visual gallery: ${OUTPUT_FILE}`);
console.log(`Total screenshots: ${screenshots.length}`);
console.log(`Test files: ${snapshotDirs.join(', ')}`);
