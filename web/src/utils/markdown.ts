import { marked } from 'marked';
import hljs from 'highlight.js/lib/core';
import { COPY_ICON } from './icons';
import { escapeHtml } from './dom';

// Import only the languages we need
import javascript from 'highlight.js/lib/languages/javascript';
import typescript from 'highlight.js/lib/languages/typescript';
import python from 'highlight.js/lib/languages/python';
import bash from 'highlight.js/lib/languages/bash';
import json from 'highlight.js/lib/languages/json';
import xml from 'highlight.js/lib/languages/xml';
import css from 'highlight.js/lib/languages/css';
import sql from 'highlight.js/lib/languages/sql';
import markdown from 'highlight.js/lib/languages/markdown';
import yaml from 'highlight.js/lib/languages/yaml';
import go from 'highlight.js/lib/languages/go';
import rust from 'highlight.js/lib/languages/rust';
import java from 'highlight.js/lib/languages/java';
import cpp from 'highlight.js/lib/languages/cpp';
import csharp from 'highlight.js/lib/languages/csharp';
import php from 'highlight.js/lib/languages/php';
import ruby from 'highlight.js/lib/languages/ruby';
import swift from 'highlight.js/lib/languages/swift';
import kotlin from 'highlight.js/lib/languages/kotlin';

// Register languages
hljs.registerLanguage('javascript', javascript);
hljs.registerLanguage('js', javascript);
hljs.registerLanguage('typescript', typescript);
hljs.registerLanguage('ts', typescript);
hljs.registerLanguage('python', python);
hljs.registerLanguage('py', python);
hljs.registerLanguage('bash', bash);
hljs.registerLanguage('sh', bash);
hljs.registerLanguage('shell', bash);
hljs.registerLanguage('json', json);
hljs.registerLanguage('xml', xml);
hljs.registerLanguage('html', xml);
hljs.registerLanguage('css', css);
hljs.registerLanguage('sql', sql);
hljs.registerLanguage('markdown', markdown);
hljs.registerLanguage('md', markdown);
hljs.registerLanguage('yaml', yaml);
hljs.registerLanguage('yml', yaml);
hljs.registerLanguage('go', go);
hljs.registerLanguage('rust', rust);
hljs.registerLanguage('rs', rust);
hljs.registerLanguage('java', java);
hljs.registerLanguage('cpp', cpp);
hljs.registerLanguage('c++', cpp);
hljs.registerLanguage('csharp', csharp);
hljs.registerLanguage('cs', csharp);
hljs.registerLanguage('php', php);
hljs.registerLanguage('ruby', ruby);
hljs.registerLanguage('rb', ruby);
hljs.registerLanguage('swift', swift);
hljs.registerLanguage('kotlin', kotlin);
hljs.registerLanguage('kt', kotlin);

// Copy button HTML for inline copy functionality
const copyButtonHtml = `<button class="inline-copy-btn" title="Copy">${COPY_ICON}</button>`;

// Configure marked with custom renderer for tables and code blocks
marked.use({
  breaks: true,
  gfm: true,
  renderer: {
    // Wrap tables in container with copy button
    table(token): string {
      // Build table header
      let headerHtml = '<thead><tr>';
      for (const cell of token.header) {
        const align = cell.align ? ` style="text-align:${cell.align}"` : '';
        headerHtml += `<th${align}>${this.parser.parseInline(cell.tokens)}</th>`;
      }
      headerHtml += '</tr></thead>';

      // Build table body
      let bodyHtml = '<tbody>';
      for (const row of token.rows) {
        bodyHtml += '<tr>';
        for (const cell of row) {
          const align = cell.align ? ` style="text-align:${cell.align}"` : '';
          bodyHtml += `<td${align}>${this.parser.parseInline(cell.tokens)}</td>`;
        }
        bodyHtml += '</tr>';
      }
      bodyHtml += '</tbody>';

      return `<div class="copyable-content table-wrapper">${copyButtonHtml}<div class="message-content-scroll-wrapper"><table>${headerHtml}${bodyHtml}</table></div></div>`;
    },

    // Wrap code blocks in container with copy button and language label
    code(token): string {
      const lang = token.lang || '';
      const langClass = lang ? `language-${escapeHtml(lang)}` : '';
      const langLabel = lang ? `<span class="code-language">${escapeHtml(lang)}</span>` : '';
      // Don't escape the code here - highlightAllCodeBlocks will handle it
      const codeHtml = escapeHtml(token.text);
      return `<div class="copyable-content code-block-wrapper">${langLabel}${copyButtonHtml}<pre><code class="${langClass}">${codeHtml}</code></pre></div>`;
    },
  },
});

/**
 * Render markdown to HTML
 */
export function renderMarkdown(text: string): string {
  return marked.parse(text) as string;
}

/**
 * Highlight code block with syntax highlighting
 */
export function highlightCode(code: string, language?: string): string {
  if (language && hljs.getLanguage(language)) {
    try {
      return hljs.highlight(code, { language }).value;
    } catch {
      // Fall through to auto-highlight
    }
  }

  try {
    return hljs.highlightAuto(code).value;
  } catch {
    return code;
  }
}

/**
 * Apply syntax highlighting to all code blocks in an element
 */
export function highlightAllCodeBlocks(element: HTMLElement): void {
  const codeBlocks = element.querySelectorAll('pre code');
  codeBlocks.forEach((block) => {
    // Get language from class (e.g., "language-javascript")
    const classes = block.className.split(' ');
    const langClass = classes.find((c) => c.startsWith('language-'));
    const language = langClass?.replace('language-', '');

    const code = block.textContent || '';
    block.innerHTML = highlightCode(code, language);
  });
}

export { hljs };