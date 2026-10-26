/**
 * Agent Editor modal component.
 * Allows creating and editing autonomous agents.
 */

import { agents, aiAssist } from '../api/agents';
import { settings } from '../api/settings';
import { useStore } from '../state/store';
import { toast } from './Toast';
import { createElement } from '../utils/dom';
import { trapTabKey } from '../utils/focus-trap';
import {
  ACTIVITY_ICON,
  CALENDAR_ICON,
  CHECKLIST_ICON,
  CLOSE_ICON,
  PHONE_ICON,
  ROBOT_ICON,
  SPARKLES_ICON,
  createIconButton,
  createIconElement,
  iconNodes,
  setIcon,
  type IconHtml,
} from '../utils/icons';
import { createLogger } from '../utils/logger';
import type { Agent, CreateAgentRequest, UpdateAgentRequest, UserSettings } from '../types/api';

const log = createLogger('agent-editor');

// Modal container element
let modalContainer: HTMLDivElement | null = null;
let currentResolve: ((result: Agent | null) => void) | null = null;
// UI-local (F2): the open editor dialog's session
let editingAgentId: string | null = null;
// The close animation's pending cleanup; a reopen runs it at once so it can't
// fire later and wipe the new session
let pendingClose: { timer: ReturnType<typeof setTimeout>; finish: () => void } | null = null;

// Available tools that agents can be granted permission for.
// Only tools that require approval for write operations are shown here.
// Always-safe tools (web_search, fetch_url, retrieve_file) and tools that
// don't affect external systems (execute_code, generate_image) are
// automatically available without needing permission selection.
const BASE_TOOLS = [
  { id: 'todoist', name: 'Todoist', description: 'Create, update, and complete tasks', icon: CHECKLIST_ICON },
  { id: 'google_calendar', name: 'Google Calendar', description: 'Create and manage calendar events', icon: CALENDAR_ICON },
  { id: 'garmin_connect', name: 'Garmin', description: 'Read sleep and readiness data', icon: ACTIVITY_ICON },
  { id: 'whatsapp', name: 'WhatsApp', description: 'Send notifications via WhatsApp', icon: PHONE_ICON },
  { id: 'trigger_agent', name: 'Other agents', description: 'Hand a task to another of your agents', icon: ROBOT_ICON },
];

// Agents created with tool_permissions = null are unrestricted (every
// available tool, including ones not in this grid). The editor must not
// silently narrow that: see getToolPermissionsForSave().
// UI-local (F2): the open editor's permission-grid edits
let originalPermissionsUnrestricted = false;
let permissionsTouched = false;

/**
 * Get available tools filtered based on user settings.
 * WhatsApp is only shown if the backend has it configured AND the user has set their phone number.
 */
function getAvailableTools(userSettings: UserSettings | null): typeof BASE_TOOLS {
  return BASE_TOOLS.filter(tool => {
    if (tool.id === 'whatsapp') {
      // WhatsApp requires both backend configuration and user phone number
      return userSettings?.whatsapp_available && userSettings?.whatsapp_phone;
    }
    return true;
  });
}

// Schedule presets for the quick option chips
const SCHEDULE_PRESETS: Array<{ cron: string; label: string; shortLabel: string }> = [
  { cron: '', label: 'Manual only', shortLabel: 'Manual' },
  { cron: '0 9 * * *', label: 'Every day at 9:00 AM', shortLabel: 'Daily 9am' },
  { cron: '0 9 * * 1-5', label: 'Weekdays at 9:00 AM', shortLabel: 'Weekdays' },
  { cron: '0 8 * * 1', label: 'Weekly on Monday at 8:00 AM', shortLabel: 'Weekly' },
];


/**
 * Validate a cron expression.
 * Returns true if valid, false otherwise.
 */
function isValidCron(cron: string): boolean {
  if (!cron) return true; // Empty is valid (manual only)

  const parts = cron.trim().split(/\s+/);
  if (parts.length !== 5) return false;

  // Regex patterns for each cron field
  const patterns = [
    /^(\*|([0-5]?\d)([-,][0-5]?\d)*|([0-5]?\d-[0-5]?\d)|(\*\/[1-5]?\d))$/, // minute (0-59)
    /^(\*|([01]?\d|2[0-3])([-,]([01]?\d|2[0-3]))*|([01]?\d|2[0-3])-([01]?\d|2[0-3])|(\*\/([01]?\d|2[0-3])))$/, // hour (0-23)
    /^(\*|([1-9]|[12]\d|3[01])([-,]([1-9]|[12]\d|3[01]))*|([1-9]|[12]\d|3[01])-([1-9]|[12]\d|3[01])|(\*\/([1-9]|[12]\d|3[01])))$/, // day of month (1-31)
    /^(\*|([1-9]|1[0-2])([-,]([1-9]|1[0-2]))*|([1-9]|1[0-2])-([1-9]|1[0-2])|(\*\/([1-9]|1[0-2])))$/, // month (1-12)
    /^(\*|[0-6]([-,][0-6])*|[0-6]-[0-6]|(\*\/[1-6]))$/, // day of week (0-6)
  ];

  for (const [i, pattern] of patterns.entries()) {
    if (!pattern.test(parts[i] ?? '')) {
      return false;
    }
  }

  return true;
}

/**
 * Initialize the agent editor.
 * Call this once during app initialization.
 */
function initAgentEditor(): void {
  if (!modalContainer) {
    modalContainer = document.createElement('div');
    modalContainer.id = 'agent-editor-modal';
    modalContainer.className = 'agent-editor-modal agent-editor-hidden';
    document.body.appendChild(modalContainer);

    // Handle click events via delegation
    modalContainer.addEventListener('click', handleModalClick);

    // Handle keyboard events
    document.addEventListener('keydown', handleModalKeydown);
  }
}

/**
 * Open the agent editor to create a new agent.
 * Note: When editing, pass an Agent with optional system_prompt if available.
 */
export async function showAgentEditor(agent?: Agent): Promise<Agent | null> {
  initAgentEditor(); // idempotent - lazy import means no boot-time init

  // Fetch user settings to determine available tools (e.g., WhatsApp)
  let userSettings: UserSettings | null = null;
  try {
    userSettings = await settings.get();
  } catch (error) {
    log.warn('Failed to fetch user settings for agent editor', { error });
    // Continue without settings - WhatsApp will just be hidden
  }

  finishPendingClose();
  return new Promise((resolve) => {
    editingAgentId = agent?.id || null;
    originalPermissionsUnrestricted = !!agent && agent.tool_permissions == null;
    permissionsTouched = false;
    currentResolve = resolve;
    renderModal(agent, userSettings);
    showModalContainer();
  });
}

/**
 * Close the agent editor.
 */
function closeAgentEditor(result: Agent | null = null): void {
  if (!modalContainer || !currentResolve) return;

  // Start exit animation
  const modalEl = modalContainer.querySelector('.agent-editor');
  if (modalEl) {
    modalEl.classList.add('agent-editor-exit');
  }
  modalContainer.classList.add('agent-editor-overlay-exit');

  // Resolve and cleanup after animation
  const finish = () => {
    pendingClose = null;
    hideModalContainer();
    if (currentResolve) {
      currentResolve(result);
      currentResolve = null;
    }
    editingAgentId = null;
  };
  pendingClose = { timer: setTimeout(finish, 150), finish };
}

/** Finish a close whose animation is still running (a reopen must not race it). */
function finishPendingClose(): void {
  if (!pendingClose) return;
  clearTimeout(pendingClose.timer);
  pendingClose.finish();
}

/** The form's initial text fields: the agent being edited, or empty for a new one. */
function agentTextValues(agent: Agent | undefined) {
  return {
    name: agent?.name || '',
    description: agent?.description || '',
    systemPrompt: agent?.system_prompt || '',
    schedule: agent?.schedule || '',
  };
}

/** The form's initial run settings: the agent being edited, or a new agent's defaults. */
function agentRunValues(agent: Agent | undefined) {
  return {
    timezone: agent?.timezone || Intl.DateTimeFormat().resolvedOptions().timeZone,
    enabled: agent?.enabled ?? true,
    // Default ON for new agents; most agents' runs are independent
    freshContext: agent?.fresh_context ?? true,
    toolPermissions: agent?.tool_permissions || [],
    model: agent?.model || useStore.getState().defaultModel,
    budgetLimit: agent?.budget_limit,
  };
}

const el = createElement;

/** An input element whose `checked` (a boolean attribute) follows `checked`. */
function checkbox(attributes: Record<string, string>, checked: boolean): HTMLInputElement {
  return el('input', { type: 'checkbox', ...attributes, ...(checked ? { checked: '' } : {}) });
}

/** A textarea holding `text`. */
function textarea(attributes: Record<string, string>, text: string): HTMLTextAreaElement {
  const field = el('textarea', attributes);
  field.textContent = text;
  return field;
}

/** An option, selected when `selected`. */
function option(value: string, label: string, selected: boolean): HTMLOptionElement {
  return el('option', { value, ...(selected ? { selected: '' } : {}) }, [label]);
}

/** A small button with an icon and a label (Parse, Enhance). */
function iconLabelButton(id: string, icon: IconHtml, label: string): HTMLButtonElement {
  return el('button', { type: 'button', id, class: 'btn btn-secondary btn-sm btn-with-icon' }, [
    iconNodes(icon),
    el('span', {}, [label]),
  ]);
}

function formGroup(children: (Node | string | false)[], extraClass = ''): HTMLElement {
  return el('div', { class: `form-group${extraClass}` }, children);
}

function help(text: string, id?: string): HTMLElement {
  return el('small', { class: 'form-help', ...(id ? { id } : {}) }, [text]);
}

/** Schedule field: preset chips, natural-language parsing, the resulting cron. */
function scheduleField(schedule: string): HTMLElement {
  // Find matching preset or mark as custom
  const matchingPreset = SCHEDULE_PRESETS.find((p) => p.cron === schedule);
  const isCustomSchedule = schedule && !matchingPreset;
  const chips = SCHEDULE_PRESETS.map((preset) =>
    el(
      'button',
      {
        type: 'button',
        class: `schedule-preset-chip ${!isCustomSchedule && schedule === preset.cron ? 'selected' : ''}`,
        'data-cron': preset.cron,
      },
      [preset.shortLabel]
    )
  );
  return formGroup([
    el('label', {}, ['Schedule']),
    el('div', { class: 'schedule-presets' }, chips),
    el('div', { class: 'schedule-natural-input' }, [
      el('input', { type: 'text', id: 'agent-schedule-natural', class: 'form-input', placeholder: 'e.g., every weekday at 9am' }),
      el('div', { class: 'form-help-row' }, [
        help('Describe when the agent should run in natural language'),
        iconLabelButton('parse-schedule-btn', SPARKLES_ICON, 'Parse'),
      ]),
    ]),
    el('div', { id: 'schedule-result', class: `schedule-result ${isCustomSchedule || schedule ? '' : 'hidden'}` }, [
      el('div', { class: 'schedule-result-info' }, [
        el('span', { id: 'schedule-explanation' }, [isCustomSchedule ? 'Custom schedule' : matchingPreset?.label || '']),
        el('span', { class: 'schedule-cron-badge' }, [
          el('code', { id: 'schedule-cron-display' }, [schedule]),
          el('button', { type: 'button', id: 'edit-cron-btn', class: 'btn-icon-tiny', title: 'Edit cron' }, ['✎']),
          el('button', { type: 'button', id: 'clear-schedule-btn', class: 'btn-icon-tiny', title: 'Clear' }, ['×']),
        ]),
      ]),
      // Block flow: the spaces between input, help and error show
      el('div', { id: 'cron-edit-container', class: 'cron-edit-container hidden' }, [
        el('input', { type: 'text', id: 'agent-cron', class: 'form-input form-input-sm', value: schedule, placeholder: '0 9 * * *' }),
        ' ',
        help('minute hour day-of-month month day-of-week', 'cron-help'),
        ' ',
        el('small', { class: 'form-error form-error--hidden', id: 'cron-error' }, ['Invalid cron expression']),
      ]),
    ]),
    el('input', { type: 'hidden', id: 'agent-schedule-value', value: schedule }),
  ]);
}

/** Model field: the models the agent can run on. */
function modelField(model: string): HTMLElement {
  const { models } = useStore.getState();
  return formGroup([
    el('label', { for: 'agent-model' }, ['Model']),
    el(
      'select',
      { id: 'agent-model', class: 'form-input form-select' },
      models.map((m) => option(m.id, `${m.name} (${m.short_name})`, model === m.id))
    ),
    help('The LLM model used when running this agent.'),
  ]);
}

/** Tool permission cards. */
function toolPermissionsField(availableTools: typeof BASE_TOOLS, toolPermissions: string[]): HTMLElement {
  // null permissions = unrestricted: render every box checked so the UI
  // tells the truth (unchecked boxes would read as "no access")
  const isToolChecked = (toolId: string): boolean =>
    originalPermissionsUnrestricted || toolPermissions.includes(toolId);
  const cards = availableTools.map((tool) =>
    el('label', { class: 'tool-permission-card' }, [
      checkbox({ name: 'tool-permission', value: tool.id }, isToolChecked(tool.id)),
      el('span', { class: 'tool-permission-content' }, [
        createIconElement('tool-icon', tool.icon),
        el('span', { class: 'tool-details' }, [
          el('span', { class: 'tool-name' }, [tool.name]),
          el('span', { class: 'tool-description' }, [tool.description]),
        ]),
        el('span', { class: 'tool-checkbox-indicator' }),
      ]),
    ])
  );
  return formGroup([
    el('label', {}, ['Tool Permissions']),
    el('div', { class: 'tool-permissions-grid' }, cards),
    help(
      originalPermissionsUnrestricted
        ? 'This agent has unrestricted tool access (including tools not listed here). Changing the selection restricts it to the checked integrations.'
        : 'Select which integrations the agent can use.'
    ),
  ]);
}

function toggle(id: string, checked: boolean, text: string): HTMLElement {
  return el('label', { class: 'toggle-label' }, [
    checkbox({ id }, checked),
    el('span', { class: 'toggle-switch' }),
    el('span', { class: 'toggle-text' }, [text]),
  ]);
}

/** Fresh context and Enabled toggles. */
function toggles(freshContext: boolean, enabled: boolean): HTMLElement[] {
  return [
    formGroup([
      toggle('agent-fresh-context', freshContext, 'Fresh context'),
      help(
        "Each run starts from a clean slate - previous runs stay readable in the conversation but aren't sent to the model (cheaper; turn off only if runs should build on each other)."
      ),
    ]),
    formGroup([toggle('agent-enabled', enabled, 'Enabled')], ' form-group-inline'),
  ];
}

/** The form's fields, top to bottom. */
function formFields(v: ReturnType<typeof agentTextValues> & ReturnType<typeof agentRunValues>, availableTools: typeof BASE_TOOLS): HTMLElement[] {
  return [
    formGroup([
      el('label', { for: 'agent-name' }, ['Name ', el('span', { class: 'required' }, ['*'])]),
      el('input', { type: 'text', id: 'agent-name', class: 'form-input', value: v.name, placeholder: 'e.g., Daily Briefing Agent', required: '' }),
      el('small', { class: 'form-error form-error--hidden', id: 'agent-name-error' }, ['Name is required']),
    ]),
    formGroup([
      el('label', { for: 'agent-description' }, ['Description']),
      textarea({ id: 'agent-description', class: 'form-input form-textarea', rows: '2', placeholder: 'What does this agent do?' }, v.description),
    ]),
    scheduleField(v.schedule),
    formGroup([
      el('label', { for: 'agent-timezone' }, ['Timezone']),
      el('select', { id: 'agent-timezone', class: 'form-input form-select' }, timezoneOptions(v.timezone)),
    ]),
    modelField(v.model),
    formGroup([
      el('label', { for: 'agent-budget-limit' }, ['Daily Budget Limit (USD)']),
      el('input', {
        type: 'number',
        id: 'agent-budget-limit',
        class: 'form-input',
        value: v.budgetLimit != null ? String(v.budgetLimit) : '',
        placeholder: 'No limit',
        min: '0',
        step: '0.01',
      }),
      help('Maximum daily spending in USD. Leave empty for no limit.'),
    ]),
    formGroup([
      el('label', { for: 'agent-system-prompt' }, ['System Prompt / Goals']),
      textarea(
        {
          id: 'agent-system-prompt',
          class: 'form-input form-textarea form-textarea--large',
          rows: '8',
          placeholder:
            'Describe what this agent should do and how it should behave. Be specific about tasks, constraints, and expected outputs...',
        },
        v.systemPrompt
      ),
      el('div', { class: 'form-help-row' }, [
        help("Define the agent's purpose, behavior, and any specific instructions."),
        iconLabelButton('enhance-prompt-btn', SPARKLES_ICON, 'Enhance'),
      ]),
    ]),
    toolPermissionsField(availableTools, v.toolPermissions),
    ...toggles(v.freshContext, v.enabled),
  ];
}

/**
 * Render the modal content.
 */
function renderModal(agent?: Agent, userSettings?: UserSettings | null): void {
  if (!modalContainer) return;

  const isEditing = !!agent;
  const title = isEditing ? 'Edit Agent' : 'Create Agent';

  // Get available tools filtered by user settings
  const availableTools = getAvailableTools(userSettings ?? null);

  const v = { ...agentTextValues(agent), ...agentRunValues(agent) };

  modalContainer.replaceChildren(
    el('div', { class: 'agent-editor', role: 'dialog', 'aria-modal': 'true', 'aria-labelledby': 'agent-editor-title' }, [
      el('div', { class: 'agent-editor-header' }, [
        el('div', { class: 'agent-editor-title-row' }, [
          createIconElement('agent-editor-icon', ROBOT_ICON),
          el('h2', { id: 'agent-editor-title', class: 'dialog-title' }, [title]),
        ]),
        createIconButton({ class: 'agent-editor-close dialog-close', 'aria-label': 'Close' }, CLOSE_ICON),
      ]),
      el('div', { class: 'agent-editor-body' }, [el('div', { class: 'agent-editor-form' }, formFields(v, availableTools))]),
      el('div', { class: 'agent-editor-footer' }, [
        isEditing && el('button', { class: 'btn btn-danger agent-editor-delete' }, ['Delete Agent']),
        el('div', { class: 'agent-editor-footer-right' }, [
          el('button', { class: 'btn btn-secondary agent-editor-cancel' }, ['Cancel']),
          el('button', { class: 'btn btn-primary agent-editor-save' }, [isEditing ? 'Save Changes' : 'Create Agent']),
        ]),
      ]),
    ])
  );

  // Setup schedule UI handlers
  setupScheduleHandlers();

  // Setup enhance prompt button handler
  setupEnhancePromptHandler();

  // Setup validation handlers
  setupValidationHandlers();

  // Track whether the user changed the permission selection - an
  // untouched unrestricted (null) selection must stay null on save
  modalContainer.querySelector('.tool-permissions-grid')?.addEventListener('change', () => {
    permissionsTouched = true;
  });
}

/**
 * The timezone options (common ones, plus the selected one if it isn't).
 */
function timezoneOptions(selected: string): HTMLOptionElement[] {
  // Common timezones
  const timezones = [
    'UTC',
    'America/New_York',
    'America/Chicago',
    'America/Denver',
    'America/Los_Angeles',
    'Europe/London',
    'Europe/Paris',
    'Europe/Berlin',
    'Europe/Prague',
    'Asia/Tokyo',
    'Asia/Shanghai',
    'Asia/Singapore',
    'Australia/Sydney',
  ];

  // Ensure selected timezone is in the list
  if (!timezones.includes(selected)) {
    timezones.push(selected);
  }

  return timezones.map((tz) => option(tz, tz.replace(/_/g, ' '), selected === tz));
}

/**
 * Get the currently selected tool permissions within the modal.
 */
function getSelectedToolPermissions(): string[] {
  if (!modalContainer) return [];

  const toolCheckboxes = modalContainer.querySelectorAll<HTMLInputElement>('input[name="tool-permission"]:checked');
  return Array.from(toolCheckboxes).map(cb => cb.value);
}

/**
 * Setup schedule UI handlers.
 */
function setupScheduleHandlers(): void {
  if (!modalContainer) return;

  const presetChips = modalContainer.querySelectorAll<HTMLButtonElement>('.schedule-preset-chip');
  const naturalInput = modalContainer.querySelector('#agent-schedule-natural') as HTMLInputElement;
  const parseBtn = modalContainer.querySelector('#parse-schedule-btn') as HTMLButtonElement;
  const scheduleResult = modalContainer.querySelector('#schedule-result') as HTMLDivElement;
  const scheduleExplanation = modalContainer.querySelector('#schedule-explanation') as HTMLSpanElement;
  const scheduleValueInput = modalContainer.querySelector('#agent-schedule-value') as HTMLInputElement;
  const cronDisplay = modalContainer.querySelector('#schedule-cron-display') as HTMLElement;
  const editCronBtn = modalContainer.querySelector('#edit-cron-btn') as HTMLButtonElement;
  const clearScheduleBtn = modalContainer.querySelector('#clear-schedule-btn') as HTMLButtonElement;
  const cronEditContainer = modalContainer.querySelector('#cron-edit-container') as HTMLDivElement;
  const cronInput = modalContainer.querySelector('#agent-cron') as HTMLInputElement;
  const timezoneSelect = modalContainer.querySelector('#agent-timezone') as HTMLSelectElement;

  // Update schedule value and UI
  const updateSchedule = (cron: string, explanation: string) => {
    scheduleValueInput.value = cron;

    if (cron) {
      cronDisplay.textContent = cron;
      scheduleExplanation.textContent = explanation;
      scheduleResult.classList.remove('hidden');
      cronInput.value = cron;
    } else {
      scheduleResult.classList.add('hidden');
    }

    // Update chip selection
    presetChips.forEach(chip => {
      const chipCron = chip.dataset.cron || '';
      chip.classList.toggle('selected', chipCron === cron);
    });
  };

  // Handle preset chip clicks
  presetChips.forEach(chip => {
    chip.addEventListener('click', () => {
      const cron = chip.dataset.cron || '';
      const preset = SCHEDULE_PRESETS.find(p => p.cron === cron);
      updateSchedule(cron, preset?.label || '');
      naturalInput.value = '';
      cronEditContainer.classList.add('hidden');
    });
  });

  // Handle parse button click
  const parseNaturalSchedule = async (): Promise<void> => {
    const text = naturalInput.value.trim();
    if (!text) {
      toast.error('Enter a schedule description');
      naturalInput.focus();
      return;
    }

    // Show loading state
    parseBtn.disabled = true;
    parseBtn.textContent = 'Parsing...';

    try {
      const timezone = timezoneSelect?.value || 'UTC';
      const result = await aiAssist.parseSchedule(text, timezone);

      if (result.error) {
        toast.error(result.error);
        return;
      }

      if (result.cron) {
        updateSchedule(result.cron, result.explanation || text);
        naturalInput.value = '';
        cronEditContainer.classList.add('hidden');
      }
    } catch (error) {
      log.error('Failed to parse schedule', { error });
      toast.error('Failed to parse schedule. Try a different description.');
    } finally {
      parseBtn.disabled = false;
      parseBtn.textContent = 'Parse';
    }
  };
  parseBtn.addEventListener('click', () => {
    void parseNaturalSchedule();
  });

  // Handle Enter key in natural input
  naturalInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      parseBtn.click();
    }
  });

  // Handle edit cron button
  editCronBtn?.addEventListener('click', () => {
    cronEditContainer.classList.toggle('hidden');
    if (!cronEditContainer.classList.contains('hidden')) {
      cronInput.focus();
      cronInput.select();
    }
  });

  // Handle cron input changes
  cronInput?.addEventListener('input', () => {
    const cron = cronInput.value.trim();
    if (cron && isValidCron(cron)) {
      scheduleValueInput.value = cron;
      cronDisplay.textContent = cron;
      scheduleExplanation.textContent = 'Custom schedule';

      // Deselect all preset chips
      presetChips.forEach(chip => chip.classList.remove('selected'));
    }
  });

  // Handle clear button
  clearScheduleBtn?.addEventListener('click', () => {
    updateSchedule('', '');
    naturalInput.value = '';
    cronEditContainer.classList.add('hidden');
  });
}

/**
 * Setup enhance prompt button handler.
 */
function setupEnhancePromptHandler(): void {
  if (!modalContainer) return;

  const enhanceBtn = modalContainer.querySelector('#enhance-prompt-btn') as HTMLButtonElement;
  const promptInput = modalContainer.querySelector('#agent-system-prompt') as HTMLTextAreaElement;
  const nameInput = modalContainer.querySelector('#agent-name') as HTMLInputElement;

  const enhancePrompt = async (): Promise<void> => {
    const prompt = promptInput?.value?.trim();
    const agentName = nameInput?.value?.trim() || 'Agent';
    const toolPermissions = getSelectedToolPermissions();

    if (!prompt) {
      toast.error('Enter a system prompt to enhance');
      promptInput?.focus();
      return;
    }

    // Show loading state
    enhanceBtn.disabled = true;
    const originalContent = Array.from(enhanceBtn.childNodes);
    setIcon(enhanceBtn, SPARKLES_ICON);
    enhanceBtn.append(createElement('span', {}, ['Enhancing...']));

    try {
      const result = await aiAssist.enhancePrompt(prompt, agentName, toolPermissions);

      if (result.error) {
        toast.error(result.error);
        return;
      }

      if (result.enhanced_prompt) {
        promptInput.value = result.enhanced_prompt;
        toast.success('Prompt enhanced');
      }
    } catch (error) {
      log.error('Failed to enhance prompt', { error });
      toast.error('Failed to enhance prompt. Try again later.');
    } finally {
      enhanceBtn.disabled = false;
      enhanceBtn.replaceChildren(...originalContent);
    }
  };
  enhanceBtn?.addEventListener('click', () => {
    void enhancePrompt();
  });
}

/**
 * Setup real-time validation handlers.
 * Clears error states when user starts typing.
 */
function setupValidationHandlers(): void {
  if (!modalContainer) return;

  const nameInput = modalContainer.querySelector('#agent-name') as HTMLInputElement;
  const nameError = modalContainer.querySelector('#agent-name-error') as HTMLElement;
  const cronInput = modalContainer.querySelector('#agent-cron') as HTMLInputElement;
  const cronError = modalContainer.querySelector('#cron-error') as HTMLElement;

  // Clear name error on input
  nameInput?.addEventListener('input', () => {
    if (nameInput.value.trim()) {
      nameInput.classList.remove('form-input--error');
      nameError?.classList.add('form-error--hidden');
    }
  });

  // Clear cron error on input and validate
  cronInput?.addEventListener('input', () => {
    const value = cronInput.value.trim();
    if (!value || isValidCron(value)) {
      cronInput.classList.remove('form-input--error');
      cronError?.classList.add('form-error--hidden');
    } else {
      cronInput.classList.add('form-input--error');
      cronError?.classList.remove('form-error--hidden');
    }
  });
}

/**
 * Handle click events on modal elements.
 */
function handleModalClick(e: MouseEvent): void {
  const target = e.target as HTMLElement;

  // Handle overlay click (close modal)
  if (target.classList.contains('agent-editor-modal')) {
    closeAgentEditor(null);
    return;
  }

  // Handle close button click
  if (target.closest('.agent-editor-close')) {
    closeAgentEditor(null);
    return;
  }

  // Handle cancel button click
  if (target.closest('.agent-editor-cancel')) {
    closeAgentEditor(null);
    return;
  }

  // Handle delete button click
  if (target.closest('.agent-editor-delete')) {
    void handleDelete();
    return;
  }

  // Handle save button click
  if (target.closest('.agent-editor-save')) {
    void handleSave();
    return;
  }
}

/**
 * Handle keyboard events for modal.
 */
function handleModalKeydown(e: KeyboardEvent): void {
  if (!modalContainer || modalContainer.classList.contains('agent-editor-hidden')) {
    return;
  }

  // Escape to close
  if (e.key === 'Escape') {
    e.preventDefault();
    closeAgentEditor(null);
    return;
  }

  // Ctrl/Cmd + Enter to save
  if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
    e.preventDefault();
    void handleSave();
    return;
  }

  // Keep Tab focus inside the editor while it is open
  trapTabKey(modalContainer, e);
}

/**
 * The trimmed agent name, or null (with the field marked) when it is empty.
 */
function validateNameField(modal: HTMLElement): string | null {
  const nameInput = modal.querySelector('#agent-name') as HTMLInputElement;
  const nameError = modal.querySelector('#agent-name-error') as HTMLElement;
  const name = nameInput?.value?.trim();

  // Clear previous errors
  nameInput?.classList.remove('form-input--error');
  nameError?.classList.add('form-error--hidden');

  if (!name) {
    nameInput?.classList.add('form-input--error');
    nameError?.classList.remove('form-error--hidden');
    nameInput?.focus();
    return null;
  }
  return name;
}

/**
 * The schedule ('' for manual only), or null (with the cron editor opened
 * on the error) when it is not a valid cron expression.
 */
function validateScheduleField(modal: HTMLElement): string | null {
  // Get schedule value from hidden input
  const scheduleValueInput = modal.querySelector('#agent-schedule-value') as HTMLInputElement;
  const schedule = scheduleValueInput?.value?.trim() || '';

  const cronInput = modal.querySelector('#agent-cron') as HTMLInputElement;
  const cronError = modal.querySelector('#cron-error') as HTMLElement;

  // Clear previous cron errors
  cronInput?.classList.remove('form-input--error');
  cronError?.classList.add('form-error--hidden');

  if (schedule && !isValidCron(schedule)) {
    cronInput?.classList.add('form-input--error');
    cronError?.classList.remove('form-error--hidden');
    // Show the cron edit container if hidden
    const cronEditContainer = modal.querySelector('#cron-edit-container') as HTMLElement;
    cronEditContainer?.classList.remove('hidden');
    cronInput?.focus();
    return null;
  }
  return schedule;
}

/** The request body from a validated form; empty optional fields are left out (same JSON as undefined). */
function readAgentForm(modal: HTMLElement, name: string, schedule: string): CreateAgentRequest | UpdateAgentRequest {
  const trimmed = (selector: string): string | undefined =>
    modal.querySelector<HTMLInputElement>(selector)?.value?.trim();
  const checked = (selector: string): boolean => modal.querySelector<HTMLInputElement>(selector)?.checked ?? true;

  const description = trimmed('#agent-description');
  const systemPrompt = trimmed('#agent-system-prompt');
  const model = modal.querySelector<HTMLSelectElement>('#agent-model')?.value;
  // Parse budget limit - empty means no limit (undefined)
  const budgetLimitValue = trimmed('#agent-budget-limit');
  const budgetLimit = budgetLimitValue ? parseFloat(budgetLimitValue) : undefined;
  const data: CreateAgentRequest | UpdateAgentRequest = {
    name,
    ...(description && { description }),
    ...(systemPrompt && { system_prompt: systemPrompt }),
    ...(schedule && { schedule }),
    timezone: modal.querySelector<HTMLSelectElement>('#agent-timezone')?.value || 'UTC',
    ...(model && { model }),
    ...(budgetLimit !== undefined && { budget_limit: budgetLimit }),
    enabled: checked('#agent-enabled'),
    fresh_context: checked('#agent-fresh-context'),
    tool_permissions: getSelectedToolPermissions(),
  };

  // An agent with unrestricted (null) permissions whose selection was
  // never touched must keep them: the PATCH treats a missing field as
  // "unchanged", while sending the checked subset would silently narrow
  // access to grid tools only
  if (originalPermissionsUnrestricted && !permissionsTouched) {
    delete data.tool_permissions;
  }
  return data;
}

/**
 * Handle save button click.
 */
async function handleSave(): Promise<void> {
  if (!modalContainer) return;

  const name = validateNameField(modalContainer);
  if (name === null) return;
  const schedule = validateScheduleField(modalContainer);
  if (schedule === null) return;
  const data = readAgentForm(modalContainer, name, schedule);

  // Disable save button during request
  const saveBtn = modalContainer.querySelector('.agent-editor-save') as HTMLButtonElement;
  if (saveBtn) {
    saveBtn.disabled = true;
    saveBtn.textContent = 'Saving...';
  }

  try {
    let result: Agent;

    if (editingAgentId) {
      // Update existing agent
      result = await agents.update(editingAgentId, data);
      toast.success('Agent updated');
    } else {
      // Create new agent
      result = await agents.create(data as CreateAgentRequest);
      toast.success('Agent created');
    }

    closeAgentEditor(result);
  } catch (error) {
    log.error('Failed to save agent', { error });
    toast.error('Failed to save agent');

    // Re-enable save button
    if (saveBtn) {
      saveBtn.disabled = false;
      saveBtn.textContent = editingAgentId ? 'Save Changes' : 'Create Agent';
    }
  }
}

/**
 * Handle delete button click with confirmation.
 */
async function handleDelete(): Promise<void> {
  if (!modalContainer || !editingAgentId) return;

  // Get agent name for confirmation message
  const nameInput = modalContainer.querySelector('#agent-name') as HTMLInputElement;
  const agentName = nameInput?.value?.trim() || 'this agent';

  // Confirm deletion
  const confirmed = confirm(
    `Delete "${agentName}"?\n\nThis will permanently delete the agent, all its messages, and execution history. Cost tracking data will be preserved.`
  );

  if (!confirmed) return;

  // Disable delete button during request
  const deleteBtn = modalContainer.querySelector('.agent-editor-delete') as HTMLButtonElement;
  if (deleteBtn) {
    deleteBtn.disabled = true;
    deleteBtn.textContent = 'Deleting...';
  }

  try {
    const agentId = editingAgentId;
    await agents.delete(agentId);
    toast.success('Agent deleted');
    closeAgentEditor(null);

    // Update the store to remove the agent
    const { removeAgent, setCommandCenterData } = useStore.getState();
    removeAgent(agentId);

    // Refresh command center data to update the UI
    try {
      const data = await agents.getCommandCenter();
      setCommandCenterData(data);

      // If we are currently in the agents view, we need to re-render it
      // The easiest way is to re-navigate to it
      if (useStore.getState().isAgentsView) {
        // dynamic: breaks import cycle (agents.ts statically imports AgentEditor.ts)
        const { navigateToAgents } = await import('../core/agents');
        await navigateToAgents(true);
      }
    } catch (error) {
      log.warn('Failed to refresh command center after deletion', { error });
    }
  } catch (error) {
    log.error('Failed to delete agent', { error });
    toast.error('Failed to delete agent');

    // Re-enable delete button
    if (deleteBtn) {
      deleteBtn.disabled = false;
      deleteBtn.textContent = 'Delete Agent';
    }
  }
}

/**
 * Show the modal container.
 */
function showModalContainer(): void {
  if (!modalContainer) return;
  modalContainer.classList.remove('agent-editor-hidden');

  // Focus name input
  requestAnimationFrame(() => {
    requestAnimationFrame(() => {
      const nameInput = modalContainer?.querySelector('#agent-name') as HTMLInputElement;
      if (nameInput) {
        nameInput.focus();
        nameInput.select();
      }
    });
  });
}

/**
 * Hide the modal container.
 */
function hideModalContainer(): void {
  if (!modalContainer) return;
  modalContainer.classList.add('agent-editor-hidden');
  modalContainer.classList.remove('agent-editor-overlay-exit');
  const modal = modalContainer.querySelector('.agent-editor');
  if (modal) {
    modal.classList.remove('agent-editor-exit');
  }
}
