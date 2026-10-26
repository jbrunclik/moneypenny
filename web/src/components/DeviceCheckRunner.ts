/**
 * The device check runner's card (admin only; the run itself is
 * core/device-checks/runner.ts). A fixed card over the top of the real chat:
 * fixed, so it changes none of the layout the checks measure. It lists the
 * scenarios with their status, asks for taps where iOS needs a real one,
 * and ends with a summary.
 */
import { createElement } from '../utils/dom';

type DeviceCheckRowStatus = 'pending' | 'running' | 'passed' | 'failed' | 'skipped' | 'error';

export interface DeviceCheckRow {
  id: string;
  title: string;
}

export interface DeviceCheckSummary {
  passed: number;
  failed: number;
  skipped: number;
  /** Why the run did not finish or was not stored (shown as is) */
  problem?: string;
}

export interface DeviceCheckRunnerView {
  setStatus(id: string, status: DeviceCheckRowStatus, detail?: string): void;
  /**
   * Show the big tap button and resolve once it was tapped. `onTap` runs
   * inside the tap's own handler: iOS opens the keyboard only for a focus()
   * made there. Rejects when `signal` aborts first.
   */
  askTap(label: string, onTap: () => void, signal: AbortSignal): Promise<void>;
  showSummary(summary: DeviceCheckSummary): void;
  close(): void;
}

const STATUS_LABELS: Record<DeviceCheckRowStatus, string> = {
  pending: 'Waiting',
  running: 'Running',
  passed: 'Passed',
  failed: 'Failed',
  skipped: 'Skipped',
  error: 'Error',
};

let card: HTMLElement | null = null;

function rowElement(row: DeviceCheckRow): HTMLLIElement {
  return createElement('li', { class: 'device-check-row', 'data-check-id': row.id, 'data-status': 'pending' }, [
    createElement('span', { class: 'device-check-row-title' }, [row.title]),
    createElement('span', { class: 'device-check-status' }, [STATUS_LABELS.pending]),
    createElement('span', { class: 'device-check-row-detail' }),
  ]);
}

function summaryText(summary: DeviceCheckSummary): string {
  const ran = summary.passed + summary.failed;
  const skipped = summary.skipped ? `, ${summary.skipped} skipped` : '';
  return `${summary.passed}/${ran} passed${skipped}`;
}

/** Open the runner card. `onStop` aborts the run; `onClose` follows Close. */
export function openDeviceCheckRunner(
  rows: readonly DeviceCheckRow[],
  handlers: { onStop: () => void; onClose: () => void }
): DeviceCheckRunnerView {
  card?.remove();
  const list = createElement('ol', { class: 'device-check-list' }, rows.map(rowElement));
  const prompt = createElement('div', { class: 'device-check-prompt hidden' });
  const footer = createElement('div', { class: 'device-check-footer' });
  const stop = createElement('button', { type: 'button', class: 'device-check-stop' }, ['Stop']);
  stop.addEventListener('click', handlers.onStop);
  const live = createElement('p', { class: 'device-check-live', 'aria-live': 'polite' }, ['Preparing…']);
  const root = createElement(
    'section',
    { class: 'device-check-card', role: 'dialog', 'aria-label': 'Device checks' },
    [createElement('header', { class: 'device-check-header' }, [createElement('h2', {}, ['Device checks']), stop]), live, list, prompt, footer]
  );
  card = root;
  document.body.appendChild(root);

  const rowOf = (id: string): HTMLElement | null => list.querySelector(`[data-check-id="${CSS.escape(id)}"]`);

  return {
    setStatus(id, status, detail) {
      const row = rowOf(id);
      if (!row) return;
      row.dataset.status = status;
      const statusEl = row.querySelector('.device-check-status');
      if (statusEl) statusEl.textContent = STATUS_LABELS[status];
      const detailEl = row.querySelector('.device-check-row-detail');
      if (detailEl) detailEl.textContent = detail ?? '';
      const title = row.querySelector('.device-check-row-title')?.textContent ?? id;
      live.textContent = `${title}: ${STATUS_LABELS[status]}`;
    },

    askTap(label, onTap, signal) {
      return new Promise<void>((resolve, reject) => {
        const button = createElement('button', { type: 'button', class: 'device-check-tap' }, [label]);
        const done = (): void => {
          prompt.classList.add('hidden');
          prompt.replaceChildren();
          signal.removeEventListener('abort', onAbort);
        };
        const onAbort = (): void => {
          done();
          reject(new Error('Device checks stopped'));
        };
        button.addEventListener('click', () => {
          // Synchronously, inside the tap: a focus() after an await opens no keyboard on iOS
          onTap();
          done();
          resolve();
        });
        prompt.replaceChildren(button);
        prompt.classList.remove('hidden');
        live.textContent = label;
        if (signal.aborted) onAbort();
        else signal.addEventListener('abort', onAbort, { once: true });
      });
    },

    showSummary(summary) {
      stop.remove();
      root.classList.add('device-check-done');
      root.classList.toggle('device-check-has-failures', summary.failed > 0 || summary.problem !== undefined);
      live.textContent = summary.problem ?? summaryText(summary);
      const close = createElement('button', { type: 'button', class: 'device-check-close' }, ['Close']);
      close.addEventListener('click', () => {
        root.remove();
        if (card === root) card = null;
        handlers.onClose();
      });
      footer.replaceChildren(close);
      close.focus();
    },

    close() {
      root.remove();
      if (card === root) card = null;
    },
  };
}
