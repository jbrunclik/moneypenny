/**
 * Quick actions: one-tap saved prompts for program conversations.
 *
 * This module owns message composition, mounting the chip bar above the
 * composer while a program conversation is open, its mobile visibility
 * rules, sending, and the editor glue. Components in
 * components/QuickActions*.ts are presentation only.
 */
import type { QuickAction } from '../types/api';

/**
 * Body, blank line, then one `Label: value` line per non-empty field (in
 * field order). Multi-line values indent continuation lines by two spaces.
 * All-empty fields -> body only.
 */
export function composeQuickActionMessage(
  action: QuickAction,
  values: Record<string, string>
): string {
  const body = action.body.trim();
  const lines: string[] = [];
  for (const field of action.fields) {
    const value = (values[field] ?? '').trim();
    if (!value) continue;
    lines.push(`${field}: ${value.split('\n').join('\n  ')}`);
  }
  return lines.length > 0 ? `${body}\n\n${lines.join('\n')}` : body;
}
