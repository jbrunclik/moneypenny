/**
 * Puts the agent's HTML into the frame's live document.
 *
 * The shell document stays in place (document.open would drop the bridge's
 * listeners): styles go to <head>, content to <body>, and every <script> is
 * re-created in document order - scripts parsed by DOMParser never run, and an
 * external one is awaited so an inline script after it can use it. Agent code
 * written for a fresh page gets synthetic DOMContentLoaded and load events.
 */

/** Inserts `script` (via `insert`) and resolves once it has run or failed. */
export type ScriptRunner = (script: HTMLScriptElement, insert: () => void) => Promise<void>;

const runScript: ScriptRunner = (script, insert) => {
  if (!script.src) {
    insert();
    return Promise.resolve();
  }
  return new Promise((resolve) => {
    script.addEventListener('load', () => resolve(), { once: true });
    script.addEventListener('error', () => resolve(), { once: true });
    insert();
  });
};

const HEAD_STYLE_SELECTOR = 'style, link[rel="stylesheet"]';
/** The bridge owns the theme attribute; an artifact cannot pin one */
const RESERVED_ROOT_ATTRIBUTES = new Set(['data-theme']);

function copyAttributes(from: Element, to: Element): void {
  for (const attr of Array.from(from.attributes)) {
    if (!RESERVED_ROOT_ATTRIBUTES.has(attr.name)) to.setAttribute(attr.name, attr.value);
  }
}

function freshScript(doc: Document, parsed: HTMLScriptElement): HTMLScriptElement {
  const script = doc.createElement('script');
  for (const attr of Array.from(parsed.attributes)) {
    script.setAttribute(attr.name, attr.value);
  }
  script.textContent = parsed.textContent;
  return script;
}

export async function loadArtifact(
  doc: Document,
  html: string,
  run: ScriptRunner = runScript
): Promise<void> {
  const parsed = new DOMParser().parseFromString(html, 'text/html');
  // A full document's <html lang class> and <body class data-* onload> apply
  copyAttributes(parsed.documentElement, doc.documentElement);
  copyAttributes(parsed.body, doc.body);
  for (const node of Array.from(parsed.head.querySelectorAll(HEAD_STYLE_SELECTOR))) {
    doc.head.appendChild(doc.adoptNode(node));
  }
  // Head scripts (a full document's) run before the body's, as in a page load
  const headScripts = Array.from(parsed.head.querySelectorAll('script'));
  for (const node of Array.from(parsed.body.childNodes)) {
    doc.body.appendChild(doc.adoptNode(node));
  }
  for (const script of headScripts) {
    const fresh = freshScript(doc, script);
    await run(fresh, () => doc.head.appendChild(fresh));
  }
  for (const script of Array.from(doc.body.querySelectorAll('script'))) {
    const fresh = freshScript(doc, script);
    await run(fresh, () => script.replaceWith(fresh));
  }
  // Bubbles like the real one, so window listeners get it too
  doc.dispatchEvent(new Event('DOMContentLoaded', { bubbles: true }));
  doc.defaultView?.dispatchEvent(new Event('load'));
}
