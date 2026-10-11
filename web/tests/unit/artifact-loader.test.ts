/**
 * The frame's loader (src/artifact/loader.ts): agent HTML into the live
 * document, scripts in order. jsdom does not execute scripts, so a fake runner
 * evaluates them; real execution is covered by the artifacts E2E spec.
 */
import { describe, it, expect, beforeEach } from 'vitest';
import { loadArtifact, type ScriptRunner } from '../../src/artifact/loader';

type Win = Record<string, unknown>;
const win = (): Win => window as unknown as Win;

/** Runs inline code; a src script "loads" after a tick and runs its data: URL.
 * The script is made inert first: jsdom would otherwise run inline code itself. */
const fakeRunner: ScriptRunner = async (script, insert) => {
  script.type = 'text/x-test';
  insert();
  const src = script.getAttribute('src');
  if (src) {
    await new Promise((r) => setTimeout(r, 5));
    new Function(decodeURIComponent(src.replace('data:text/javascript,', '')))();
    return;
  }
  try {
    new Function(script.textContent ?? '')();
  } catch {
    // A browser reports it to window.onerror and carries on
  }
};

beforeEach(() => {
  document.head.innerHTML = '';
  document.body.innerHTML = '';
  document.body.removeAttribute('class');
  document.body.removeAttribute('data-servings');
  document.documentElement.removeAttribute('lang');
  document.documentElement.removeAttribute('class');
  for (const key of ['__a', '__b', '__order', '__ready']) delete win()[key];
});

describe('loadArtifact', () => {
  it('renders a fragment into the body', async () => {
    await loadArtifact(document, '<div class="mp-card"><h2>Tips</h2></div>', fakeRunner);
    expect(document.body.querySelector('.mp-card h2')?.textContent).toBe('Tips');
  });

  it('puts a full document’s styles in head and its content in body', async () => {
    const html =
      '<!doctype html><html><head><title>x</title><style>.a{color:red}</style></head>' +
      '<body><p class="a">hi</p></body></html>';
    await loadArtifact(document, html, fakeRunner);
    expect(document.head.querySelector('style')?.textContent).toBe('.a{color:red}');
    expect(document.body.querySelector('p.a')?.textContent).toBe('hi');
    expect(document.body.querySelector('title')).toBeNull();
  });

  it('keeps a full document’s <html> and <body> attributes', async () => {
    const html = '<html lang="cs" class="x"><body class="recipe" data-servings="4"><p>hi</p></body></html>';
    await loadArtifact(document, html, fakeRunner);
    expect(document.body.classList.contains('recipe')).toBe(true);
    expect(document.body.dataset.servings).toBe('4');
    expect(document.documentElement.getAttribute('lang')).toBe('cs');
    expect(document.documentElement.classList.contains('x')).toBe(true);
  });

  it('never lets the artifact replace the theme attribute', async () => {
    document.documentElement.dataset.theme = 'light';
    await loadArtifact(document, '<html data-theme="dark"><body></body></html>', fakeRunner);
    expect(document.documentElement.dataset.theme).toBe('light');
    delete document.documentElement.dataset.theme;
  });

  it('runs inline scripts in document order', async () => {
    const html =
      '<script>window.__order = ["one"]</script><p>x</p><script>window.__order.push("two")</script>';
    await loadArtifact(document, html, fakeRunner);
    expect(win().__order).toEqual(['one', 'two']);
  });

  it('waits for an external script before the inline script after it', async () => {
    const html =
      '<script src="data:text/javascript,window.__a=1"></script><script>window.__b=window.__a+1</script>';
    await loadArtifact(document, html, fakeRunner);
    expect(win().__b).toBe(2);
  });

  it('a throwing script does not stop the next one', async () => {
    const html = '<script>throw new Error("boom")</script><script>window.__b = 3</script>';
    await loadArtifact(document, html, fakeRunner);
    expect(win().__b).toBe(3);
  });

  it('fires DOMContentLoaded for code listening on window too', async () => {
    const html =
      '<script>window.addEventListener("DOMContentLoaded", () => { window.__ready = true })</script>';
    await loadArtifact(document, html, fakeRunner);
    expect(win().__ready).toBe(true);
  });

  it('fires DOMContentLoaded for agent code that waits for it', async () => {
    const html =
      '<script>document.addEventListener("DOMContentLoaded", () => { window.__ready = true })</script>';
    await loadArtifact(document, html, fakeRunner);
    expect(win().__ready).toBe(true);
  });

  it('replaces each script with a fresh element (DOMParser scripts never run)', async () => {
    const seen: HTMLScriptElement[] = [];
    await loadArtifact(document, '<script>1</script>', async (script, insert) => {
      seen.push(script);
      insert();
    });
    expect(seen).toHaveLength(1);
    // A leading script parses into <head>, where it runs (as in a page load)
    expect(document.querySelector('script')).toBe(seen[0]);
  });
});
