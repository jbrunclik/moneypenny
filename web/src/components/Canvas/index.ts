import { useStore } from '../../state/store';
import { getElementById } from '../../utils/dom';
import { saveCurrentCanvas, downloadCanvas } from '../../core/canvas';

/**
 * Initialize Canvas component
 */
export function initCanvas(): void {
  const panel = getElementById('canvas-panel');
  const editor = getElementById<HTMLTextAreaElement>('canvas-editor');
  const title = getElementById('canvas-title');
  const saveBtn = getElementById('canvas-save');
  const downloadBtn = getElementById('canvas-download');
  const closeBtn = getElementById('canvas-close');
  const statusEl = getElementById('canvas-status');
  const main = getElementById('main');

  if (!panel || !editor || !title || !main) return;

  // Subscribe to canvas open/close
  useStore.subscribe(
    (state) => state.isCanvasOpen,
    (isOpen) => {
      panel.classList.toggle('hidden', !isOpen);
      main.classList.toggle('canvas-open', isOpen);
    }
  );

  // Subscribe to current canvas
  useStore.subscribe(
    (state) => state.currentCanvas,
    (canvas) => {
      if (!canvas) return;
      title.textContent = canvas.title;
      editor.value = canvas.content;
    }
  );

  // Subscribe to dirty state
  useStore.subscribe(
    (state) => state.canvasDirty,
    (dirty) => {
      if (statusEl) {
        statusEl.textContent = dirty ? 'Unsaved changes' : 'Saved';
        statusEl.classList.toggle('dirty', dirty);
      }
    }
  );

  // Editor changes
  editor.addEventListener('input', () => {
    useStore.getState().updateCanvasContent(editor.value);
  });

  // Save button
  saveBtn?.addEventListener('click', async () => {
    await saveCurrentCanvas();
  });

  // Download button
  downloadBtn?.addEventListener('click', () => {
    downloadCanvas();
  });

  // Close button
  closeBtn?.addEventListener('click', () => {
    useStore.getState().closeCanvas();
  });

  // Keyboard shortcuts
  document.addEventListener('keydown', (e) => {
    if (!useStore.getState().isCanvasOpen) return;

    // Ctrl+S / Cmd+S - Save
    if ((e.ctrlKey || e.metaKey) && e.key === 's') {
      e.preventDefault();
      saveCurrentCanvas();
    }

    // Esc - Close canvas
    if (e.key === 'Escape') {
      useStore.getState().closeCanvas();
    }
  });
}
