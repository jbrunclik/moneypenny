/**
 * Mermaid diagrams in answers: ```mermaid code blocks become SVG diagrams.
 *
 * The library (~2 MB) is imported only when a message actually contains a
 * diagram, and only for finished messages (never per streamed token). It runs
 * with securityLevel 'strict' and SVG text labels, and the SVG is sanitized
 * again with DOMPurify (diagram source is model output). A
 * block that does not parse stays the code block it was; the source stays in
 * the DOM (hidden) so the block's copy button still copies it.
 */
import DOMPurify from 'dompurify';
import { createLogger } from './logger';

const log = createLogger('mermaid');

const BLOCK_SELECTOR = '.code-block-wrapper:not([data-mermaid]) code.language-mermaid';
let counter = 0;

type MermaidApi = (typeof import('mermaid'))['default'];
let loading: Promise<MermaidApi> | null = null;

function loadMermaid(): Promise<MermaidApi> {
  loading ??= import('mermaid').then((module) => module.default);
  return loading;
}

/**
 * Mermaid's base theme fed from the app's tokens, so a diagram looks like the
 * app in both themes (its own dark theme adds label boxes and node glows).
 * The app is dark unless the user picked light (theme.ts).
 */
function themeVariables(): Record<string, string | boolean> {
  // Tokens are often var(--color-...) chains: resolve them to a concrete
  // colour through a probe element (mermaid parses rgb()/hex, not var())
  const probe = document.createElement('span');
  probe.style.display = 'none';
  document.body.appendChild(probe);
  const token = (name: string, fallback: string): string => {
    probe.style.color = '';
    probe.style.color = `var(${name})`;
    const resolved = getComputedStyle(probe).color;
    return resolved && !resolved.startsWith('var(') ? resolved : fallback;
  };
  const dark = document.documentElement.getAttribute('data-theme') !== 'light';
  const surface = token('--bg-tertiary', dark ? '#262626' : '#f0f0f3');
  const variables = {
    darkMode: dark,
    background: surface,
    primaryColor: token('--bg-secondary', dark ? '#171717' : '#f7f7f9'),
    primaryTextColor: token('--text-primary', dark ? '#f5f5f5' : '#171717'),
    primaryBorderColor: token('--accent', '#5753e8'),
    secondaryColor: token('--bg-secondary', dark ? '#171717' : '#f7f7f9'),
    tertiaryColor: surface,
    lineColor: token('--text-muted', '#8a8a8a'),
    textColor: token('--text-primary', dark ? '#f5f5f5' : '#171717'),
    edgeLabelBackground: surface,
    fontFamily: getComputedStyle(document.body).fontFamily,
    fontSize: '14px',
  };
  probe.remove();
  return variables;
}

/** Draw every not-yet-drawn mermaid block inside an element. */
export async function renderMermaidIn(element: HTMLElement): Promise<void> {
  const blocks = [...element.querySelectorAll<HTMLElement>(BLOCK_SELECTOR)];
  if (!blocks.length) return;
  const mermaid = await loadMermaid();
  // SVG text labels (no HTML in foreignObject) so the SVG sanitizer keeps them
  mermaid.initialize({
    startOnLoad: false,
    securityLevel: 'strict',
    htmlLabels: false,
    theme: 'base',
    look: 'classic', // flat nodes: the default look adds shadows that glow on dark
    themeVariables: themeVariables(),
  });
  for (const code of blocks) {
    const wrapper = code.closest<HTMLElement>('.code-block-wrapper');
    if (!wrapper || wrapper.dataset.mermaid) continue;
    wrapper.dataset.mermaid = 'pending';
    try {
      counter += 1;
      const { svg } = await mermaid.render(`mermaid-${counter}`, code.textContent ?? '');
      const diagram = document.createElement('div');
      diagram.className = 'mermaid-diagram';
      // Diagram source is model output: sanitize again on top of mermaid's strict mode
      diagram.innerHTML = DOMPurify.sanitize(svg, { USE_PROFILES: { svg: true, svgFilters: true } });
      wrapper.prepend(diagram);
      wrapper.classList.add('code-block-wrapper--diagram');
      wrapper.dataset.mermaid = 'drawn';
    } catch (error) {
      // Not valid mermaid: keep showing the code
      log.debug('Mermaid block did not render', { error });
      wrapper.dataset.mermaid = 'failed';
    }
  }
}
