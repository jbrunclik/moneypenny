import { useStore } from '../state/store';
import { isCanvasFile } from '../types/api';

/**
 * Open a Canvas document from a message file
 */
export async function openCanvasFromMessage(
  messageId: string,
  fileIndex: number
): Promise<void> {
  try {
    // Fetch file content
    const response = await fetch(`/api/messages/${messageId}/files/${fileIndex}`);
    if (!response.ok) throw new Error('Failed to load canvas');

    const blob = await response.blob();
    const content = await blob.text();

    // Get metadata from store
    const store = useStore.getState();
    const messages = store.getMessages(store.currentConversation?.id || '');
    const message = messages.find((m) => m.id === messageId);
    const file = message?.files?.[fileIndex];

    if (!file || !isCanvasFile(file)) {
      throw new Error('Not a canvas file');
    }

    // Extract title from filename (remove .md extension)
    const title = file.name.replace(/\.md$/, '');

    // Open canvas
    store.openCanvas(messageId, fileIndex, title, content);
  } catch (error) {
    console.error('Failed to open canvas:', error);
    alert('Failed to open canvas');
  }
}

/**
 * Open the most recent Canvas document in current conversation
 */
export function openMostRecentCanvas(): void {
  const store = useStore.getState();
  const messages = store.getMessages(store.currentConversation?.id || '');

  // Search from newest to oldest
  for (let i = messages.length - 1; i >= 0; i--) {
    const message = messages[i];
    if (!message.files) continue;

    const canvasIndex = message.files.findIndex(isCanvasFile);
    if (canvasIndex !== -1) {
      openCanvasFromMessage(message.id, canvasIndex);
      return;
    }
  }

  alert('No canvas documents found in this conversation');
}

/**
 * Save current Canvas to server
 */
export async function saveCurrentCanvas(): Promise<void> {
  const state = useStore.getState();
  const { currentCanvas, canvasContent } = state;
  if (!currentCanvas) return;

  try {
    const response = await fetch(
      `/api/messages/${currentCanvas.messageId}/files/${currentCanvas.fileIndex}`,
      {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ content: canvasContent }),
      }
    );

    if (!response.ok) throw new Error('Save failed');

    state.markCanvasSaved();
    // Update saved content
    state.openCanvas(
      currentCanvas.messageId,
      currentCanvas.fileIndex,
      currentCanvas.title,
      canvasContent
    );
  } catch (error) {
    console.error('Failed to save canvas:', error);
    alert('Failed to save canvas');
  }
}

/**
 * Download current Canvas as file
 */
export function downloadCanvas(): void {
  const { currentCanvas, canvasContent } = useStore.getState();
  if (!currentCanvas) return;

  const blob = new Blob([canvasContent], { type: 'text/markdown' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `${currentCanvas.title}.md`;
  a.click();
  URL.revokeObjectURL(url);
}
