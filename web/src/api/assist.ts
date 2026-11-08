/**
 * AI-assist helpers for the standing chat editor: natural-language schedule
 * parsing and the prompt enhancer.
 */
import type { EnhancePromptRequest, EnhancePromptResponse, ParseScheduleResponse } from '../types/api';
import { request } from './http';

// AI Assist endpoints
export const aiAssist = {
  /**
   * Parse a natural language schedule description into a cron expression.
   * Uses an LLM to interpret the input.
   * @param naturalLanguage - Natural language description (e.g., "every day at 9am")
   * @param timezone - IANA timezone for interpreting the schedule (default: UTC)
   */
  async parseSchedule(naturalLanguage: string, timezone: string = 'UTC'): Promise<ParseScheduleResponse> {
    return request<ParseScheduleResponse>('/api/ai-assist/parse-schedule', {
      method: 'POST',
      body: JSON.stringify({
        natural_language: naturalLanguage,
        timezone,
      }),
    });
  },

  /**
   * Enhance a system prompt using AI.
   * Takes a basic prompt and improves it with clearer instructions.
   * @param prompt - Current system prompt to enhance
   * @param agentName - Name of the agent (for context)
   */
  async enhancePrompt(
    prompt: string,
    agentName: string,
    toolPermissions?: string[]
  ): Promise<EnhancePromptResponse> {
    const body: EnhancePromptRequest = {
      prompt,
      agent_name: agentName,
    };

    if (toolPermissions !== undefined) {
      body.tool_permissions = toolPermissions;
    }

    return request<EnhancePromptResponse>('/api/ai-assist/enhance-prompt', {
      method: 'POST',
      body: JSON.stringify(body),
    });
  },
};
