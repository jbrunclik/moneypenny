/**
 * Agent Editor modal component.
 * Allows creating and editing autonomous agents.
 */

import { agents, aiAssist, settings } from '../api/client';
import { useStore } from '../state/store';
import { toast } from './Toast';
import { escapeHtml } from '../utils/dom';
import {
  CALENDAR_ICON,
  CHECKLIST_ICON,
  CLOSE_ICON,
  PHONE_ICON,
  ROBOT_ICON,
  SPARKLES_ICON,
} from '../utils/icons';
import { createLogger } from '../utils/logger';
import type { Agent, CreateAgentRequest, UpdateAgentRequest, UserSettings } from '../types/api';

const log = createLogger('agent-editor');

// Modal container element
let modalContainer: HTMLDivElement | null = null;
let currentResolve: ((result: Agent | null) => void) | null = null;
let editingAgentId: string | null = null;

// Available tools that agents can be granted permission for.
// Only tools that require approval for write operations are shown here.
// Always-safe tools (web_search, fetch_url, retrieve_file) and tools that
// don't affect external systems (execute_code, generate_image) are
// automatically available without needing permission selection.
const BASE_TOOLS = [
  { id: 'todoist', name: 'Todoist', description: 'Create, update, and complete tasks', icon: CHECKLIST_ICON },
  { id: 'google_calendar', name: 'Google Calendar', description: 'Create and manage calendar events', icon: CALENDAR_ICON },
  { id: 'whatsapp', name: 'WhatsApp', description: 'Send notifications via WhatsApp', icon: PHONE_ICON },
];

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

  for (let i = 0; i < 5; i++) {
    if (!patterns[i].test(parts[i])) {
      return false;
    }
  }

  return true;
}

/**
 * Initialize the agent editor.
 * Call this once during app initialization.
 */
export function initAgentEditor(): void {
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
  // Fetch user settings to determine available tools (e.g., WhatsApp)
  let userSettings: UserSettings | null = null;
  try {
    userSettings = await settings.get();
  } catch (error) {
    log.warn('Failed to fetch user settings for agent editor', { error });
    // Continue without settings - WhatsApp will just be hidden
  }

  return new Promise((resolve) => {
    editingAgentId = agent?.id || null;
    currentResolve = resolve;
    renderModal(agent, userSettings);
    showModalContainer();
  });
}

/**
 * Close the agent editor.
 */
export function closeAgentEditor(result: Agent | null = null): void {
  if (!modalContainer || !currentResolve) return;

  // Start exit animation
  const modalEl = modalContainer.querySelector('.agent-editor');
  if (modalEl) {
    modalEl.classList.add('agent-editor-exit');
  }
  modalContainer.classList.add('agent-editor-overlay-exit');

  // Resolve and cleanup after animation
  setTimeout(() => {
    hideModalContainer();
    if (currentResolve) {
      currentResolve(result);
      currentResolve = null;
    }
    editingAgentId = null;
  }, 150);
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

  // Get initial values
  const name = agent?.name || '';
  const description = agent?.description || '';
  const systemPrompt = agent?.system_prompt || '';
  const schedule = agent?.schedule || '';
  const timezone = agent?.timezone || Intl.DateTimeFormat().resolvedOptions().timeZone;
  const enabled = agent?.enabled ?? true;
  const toolPermissions = agent?.tool_permissions || [];
  const { models, defaultModel } = useStore.getState();
  const model = agent?.model || defaultModel;
  const budgetLimit = agent?.budget_limit;

  // Find matching preset or mark as custom
  const matchingPreset = SCHEDULE_PRESETS.find(p => p.cron === schedule);
  const isCustomSchedule = schedule && !matchingPreset;

  modalContainer.innerHTML = `
    <div class="agent-editor" role="dialog" aria-modal="true" aria-labelledby="agent-editor-title">
      <div class="agent-editor-header">
        <div class="agent-editor-title-row">
          <span class="agent-editor-icon">${ROBOT_ICON}</span>
          <h2 id="agent-editor-title">${escapeHtml(title)}</h2>
        </div>
        <button class="agent-editor-close" aria-label="Close">${CLOSE_ICON}</button>
      </div>

      <div class="agent-editor-body">
        <div class="agent-editor-form">
          <div class="form-group">
            <label for="agent-name">Name <span class="required">*</span></label>
            <input type="text" id="agent-name" class="form-input" value="${escapeHtml(name)}" placeholder="e.g., Daily Briefing Agent" required>
            <small class="form-error form-error--hidden" id="agent-name-error">Name is required</small>
          </div>

          <div class="form-group">
            <label for="agent-description">Description</label>
            <textarea id="agent-description" class="form-input form-textarea" rows="2" placeholder="What does this agent do?">${escapeHtml(description)}</textarea>
          </div>

          <div class="form-group">
            <label>Schedule</label>
            <div class="schedule-presets">
              ${SCHEDULE_PRESETS.map(preset => `
                <button type="button" class="schedule-preset-chip ${!isCustomSchedule && schedule === preset.cron ? 'selected' : ''}" data-cron="${escapeHtml(preset.cron)}">
                  ${escapeHtml(preset.shortLabel)}
                </button>
              `).join('')}
            </div>
            <div class="schedule-natural-input">
              <input type="text" id="agent-schedule-natural" class="form-input" placeholder="e.g., every weekday at 9am">
              <div class="form-help-row">
                <small class="form-help">Describe when the agent should run in natural language</small>
                <button type="button" id="parse-schedule-btn" class="btn btn-secondary btn-sm btn-with-icon">
                  ${SPARKLES_ICON}
                  <span>Parse</span>
                </button>
              </div>
            </div>
            <div id="schedule-result" class="schedule-result ${isCustomSchedule || schedule ? '' : 'hidden'}">
              <div class="schedule-result-info">
                <span id="schedule-explanation">${isCustomSchedule ? 'Custom schedule' : matchingPreset?.label || ''}</span>
                <span class="schedule-cron-badge">
                  <code id="schedule-cron-display">${escapeHtml(schedule)}</code>
                  <button type="button" id="edit-cron-btn" class="btn-icon-tiny" title="Edit cron">✎</button>
                  <button type="button" id="clear-schedule-btn" class="btn-icon-tiny" title="Clear">×</button>
                </span>
              </div>
              <div id="cron-edit-container" class="cron-edit-container hidden">
                <input type="text" id="agent-cron" class="form-input form-input-sm" value="${escapeHtml(schedule)}" placeholder="0 9 * * *">
                <small class="form-help" id="cron-help">minute hour day-of-month month day-of-week</small>
                <small class="form-error form-error--hidden" id="cron-error">Invalid cron expression</small>
              </div>
            </div>
            <input type="hidden" id="agent-schedule-value" value="${escapeHtml(schedule)}">
          </div>

          <div class="form-group">
            <label for="agent-timezone">Timezone</label>
            <select id="agent-timezone" class="form-input form-select">
              ${getTimezoneOptions(timezone)}
            </select>
          </div>

          <div class="form-group">
            <label for="agent-model">Model</label>
            <select id="agent-model" class="form-input form-select">
              ${models.map(m => `
                <option value="${escapeHtml(m.id)}" ${model === m.id ? 'selected' : ''}>
                  ${escapeHtml(m.name)} (${escapeHtml(m.short_name)})
                </option>
              `).join('')}
            </select>
            <small class="form-help">The LLM model used when running this agent.</small>
          </div>

          <div class="form-group">
            <label for="agent-budget-limit">Daily Budget Limit (USD)</label>
            <input type="number" id="agent-budget-limit" class="form-input" value="${budgetLimit != null ? budgetLimit : ''}" placeholder="No limit" min="0" step="0.01">
            <small class="form-help">Maximum daily spending in USD. Leave empty for no limit.</small>
          </div>

          <div class="form-group">
            <label for="agent-system-prompt">System Prompt / Goals</label>
            <textarea id="agent-system-prompt" class="form-input form-textarea form-textarea--large" rows="8" placeholder="Describe what this agent should do and how it should behave. Be specific about tasks, constraints, and expected outputs...">${escapeHtml(systemPrompt)}</textarea>
            <div class="form-help-row">
              <small class="form-help">Define the agent's purpose, behavior, and any specific instructions.</small>
              <button type="button" id="enhance-prompt-btn" class="btn btn-secondary btn-sm btn-with-icon">
                ${SPARKLES_ICON}
                <span>Enhance</span>
              </button>
            </div>
          </div>

          <div class="form-group">
            <label>Tool Permissions</label>
            <div class="tool-permissions-grid">
              ${availableTools.map(tool => `
                <label class="tool-permission-card">
                  <input type="checkbox" name="tool-permission" value="${escapeHtml(tool.id)}" ${toolPermissions.includes(tool.id) ? 'checked' : ''}>
                  <span class="tool-permission-content">
                    <span class="tool-icon">${tool.icon}</span>
                    <span class="tool-details">
                      <span class="tool-name">${escapeHtml(tool.name)}</span>
                      <span class="tool-description">${escapeHtml(tool.description)}</span>
                    </span>
                    <span class="tool-checkbox-indicator"></span>
                  </span>
                </label>
              `).join('')}
            </div>
            <small class="form-help">Select which integrations the agent can use.</small>
          </div>

          <div class="form-group form-group-inline">
            <label class="toggle-label">
              <input type="checkbox" id="agent-enabled" ${enabled ? 'checked' : ''}>
              <span class="toggle-switch"></span>
              <span class="toggle-text">Enabled</span>
            </label>
          </div>
        </div>
      </div>

      <div class="agent-editor-footer">
        ${isEditing ? '<button class="btn btn-danger agent-editor-delete">Delete Agent</button>' : ''}
        <div class="agent-editor-footer-right">
          <button class="btn btn-secondary agent-editor-cancel">Cancel</button>
          <button class="btn btn-primary agent-editor-save">
            ${isEditing ? 'Save Changes' : 'Create Agent'}
          </button>
        </div>
      </div>
    </div>
  `;

  // Setup schedule UI handlers
  setupScheduleHandlers();

  // Setup enhance prompt button handler
  setupEnhancePromptHandler();

  // Setup validation handlers
  setupValidationHandlers();
}

/**
 * Get timezone options HTML.
 */
function getTimezoneOptions(selected: string): string {
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

  return timezones.map(tz => `
    <option value="${escapeHtml(tz)}" ${selected === tz ? 'selected' : ''}>
      ${escapeHtml(tz.replace(/_/g, ' '))}
    </option>
  `).join('');
}

/**
 * Get the currently selected tool permissions within the modal.
 */
function getSelectedToolPermissions(): string[] {
  if (!modalContainer) return [];

  const toolCheckboxes = modalContainer.querySelectorAll('input[name="tool-permission"]:checked') as NodeListOf<HTMLInputElement>;
  return Array.from(toolCheckboxes).map(cb => cb.value);
}

/**
 * Setup schedule UI handlers.
 */
function setupScheduleHandlers(): void {
  if (!modalContainer) return;

  const presetChips = modalContainer.querySelectorAll('.schedule-preset-chip') as NodeListOf<HTMLButtonElement>;
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
  parseBtn.addEventListener('click', async () => {
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

  enhanceBtn?.addEventListener('click', async () => {
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
    const originalContent = enhanceBtn.innerHTML;
    enhanceBtn.innerHTML = `${SPARKLES_ICON}<span>Enhancing...</span>`;

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
      enhanceBtn.innerHTML = originalContent;
    }
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
    handleDelete();
    return;
  }

  // Handle save button click
  if (target.closest('.agent-editor-save')) {
    handleSave();
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
    handleSave();
    return;
  }
}

/**
 * Handle save button click.
 */
async function handleSave(): Promise<void> {
  if (!modalContainer) return;

  // Get form values
  const nameInput = modalContainer.querySelector('#agent-name') as HTMLInputElement;
  const descriptionInput = modalContainer.querySelector('#agent-description') as HTMLTextAreaElement;
  const systemPromptInput = modalContainer.querySelector('#agent-system-prompt') as HTMLTextAreaElement;
  const scheduleValueInput = modalContainer.querySelector('#agent-schedule-value') as HTMLInputElement;
  const timezoneSelect = modalContainer.querySelector('#agent-timezone') as HTMLSelectElement;
  const modelSelect = modalContainer.querySelector('#agent-model') as HTMLSelectElement;
  const budgetLimitInput = modalContainer.querySelector('#agent-budget-limit') as HTMLInputElement;
  const enabledInput = modalContainer.querySelector('#agent-enabled') as HTMLInputElement;

  const name = nameInput?.value?.trim();
  const nameError = modalContainer.querySelector('#agent-name-error') as HTMLElement;

  // Clear previous errors
  nameInput?.classList.remove('form-input--error');
  nameError?.classList.add('form-error--hidden');

  if (!name) {
    nameInput?.classList.add('form-input--error');
    nameError?.classList.remove('form-error--hidden');
    nameInput?.focus();
    return;
  }

  // Get schedule value from hidden input
  const schedule = scheduleValueInput?.value?.trim() || '';

  // Validate cron expression
  const cronInput = modalContainer.querySelector('#agent-cron') as HTMLInputElement;
  const cronError = modalContainer.querySelector('#cron-error') as HTMLElement;

  // Clear previous cron errors
  cronInput?.classList.remove('form-input--error');
  cronError?.classList.add('form-error--hidden');

  if (schedule && !isValidCron(schedule)) {
    cronInput?.classList.add('form-input--error');
    cronError?.classList.remove('form-error--hidden');
    // Show the cron edit container if hidden
    const cronEditContainer = modalContainer.querySelector('#cron-edit-container') as HTMLElement;
    cronEditContainer?.classList.remove('hidden');
    cronInput?.focus();
    return;
  }

  // Get tool permissions
  const toolPermissions = getSelectedToolPermissions();

  // Parse budget limit - empty means no limit (undefined)
  const budgetLimitValue = budgetLimitInput?.value?.trim();
  const budgetLimit = budgetLimitValue ? parseFloat(budgetLimitValue) : undefined;

  const data: CreateAgentRequest | UpdateAgentRequest = {
    name,
    description: descriptionInput?.value?.trim() || undefined,
    system_prompt: systemPromptInput?.value?.trim() || undefined,
    schedule: schedule || undefined,
    timezone: timezoneSelect?.value || 'UTC',
    model: modelSelect?.value || undefined,
    budget_limit: budgetLimit,
    enabled: enabledInput?.checked ?? true,
    tool_permissions: toolPermissions,
  };

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
