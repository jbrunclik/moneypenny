/**
 * Characterization of the iOS/iPad hardware-keyboard listener in
 * initMessageInput: typing anywhere focuses the composer, except from a
 * field, for modifier/navigation keys, and with Ctrl/Alt/Meta held.
 * Only verifiable on a real iPad with a keyboard, so a refactor must leave
 * this recording identical.
 */
import { afterEach, describe, expect, it, vi } from 'vitest';
import { initMessageInput } from '@/components/MessageInput';

describe('iOS hardware keyboard focuses the composer', () => {
  const originalNavigator = window.navigator;

  afterEach(() => {
    Object.defineProperty(window, 'navigator', { value: originalNavigator, configurable: true, writable: true });
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it('records which keydowns focus the input', () => {
    Object.defineProperty(window, 'navigator', {
      value: { ...originalNavigator, userAgent: 'Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X)', platform: 'iPhone', maxTouchPoints: 5 },
      configurable: true,
      writable: true,
    });
    vi.stubGlobal('matchMedia', () => ({ matches: false }));
    document.body.innerHTML = `
      <textarea id="message-input"></textarea><button id="send-btn"></button>
      <input id="other"><div id="editable" contenteditable="true"></div><div id="plain"></div>`;
    const input = document.getElementById('message-input') as HTMLTextAreaElement;
    initMessageInput(() => {});
    let focused = 0;
    vi.spyOn(input, 'focus').mockImplementation(() => {
      focused++;
    });

    const results: string[] = [];
    const press = (targetId: string, key: string, mods: KeyboardEventInit = {}): void => {
      const before = focused;
      const target = document.getElementById(targetId) as HTMLElement;
      target.dispatchEvent(new KeyboardEvent('keydown', { key, bubbles: true, ...mods }));
      results.push(`${targetId} ${key} ${JSON.stringify(mods)} -> ${focused > before ? 'focus' : 'skip'}`);
    };
    const keys = [
      'a', 'Z', '1', ' ', 'Enter', 'Backspace',
      'Shift', 'Control', 'Alt', 'Meta', 'Escape', 'Tab', 'CapsLock',
      'ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight',
    ];
    for (const key of keys) press('plain', key);
    press('plain', 'a', { shiftKey: true });
    press('plain', 'a', { ctrlKey: true });
    press('plain', 'a', { altKey: true });
    press('plain', 'a', { metaKey: true });
    press('other', 'a');
    press('message-input', 'a');
    press('editable', 'a'); // jsdom has no isContentEditable: focuses here, skips on a device
    expect(results).toMatchInlineSnapshot(`
      [
        "plain a {} -> focus",
        "plain Z {} -> focus",
        "plain 1 {} -> focus",
        "plain   {} -> focus",
        "plain Enter {} -> focus",
        "plain Backspace {} -> focus",
        "plain Shift {} -> skip",
        "plain Control {} -> skip",
        "plain Alt {} -> skip",
        "plain Meta {} -> skip",
        "plain Escape {} -> skip",
        "plain Tab {} -> skip",
        "plain CapsLock {} -> skip",
        "plain ArrowUp {} -> skip",
        "plain ArrowDown {} -> skip",
        "plain ArrowLeft {} -> skip",
        "plain ArrowRight {} -> skip",
        "plain a {"shiftKey":true} -> focus",
        "plain a {"ctrlKey":true} -> skip",
        "plain a {"altKey":true} -> skip",
        "plain a {"metaKey":true} -> skip",
        "other a {} -> skip",
        "message-input a {} -> skip",
        "editable a {} -> focus",
      ]
    `);
  });
});
