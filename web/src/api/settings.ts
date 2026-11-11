/**
 * User settings API.
 */
import { QUICK_ACTION_REVIEW_TIMEOUT_MS } from "../config";
import {
  type InstructionsChangeResponse,
  type SetupReviewResponse,
  type SetupSuggestion,
  type UserSettings,
} from "../types/api";
import { request, requestWithRetry } from "./http";
import { refreshedOr, retryDropped, reviewErrorText } from "./setup-review";

// Settings endpoints
export const settings = {
  async get(): Promise<UserSettings> {
    return requestWithRetry<UserSettings>("/api/users/me/settings");
  },

  async update(data: Partial<UserSettings>): Promise<void> {
    // PATCH is idempotent (same update = same result), safe to retry
    await request<{ status: string }>("/api/users/me/settings", {
      method: "PATCH",
      body: JSON.stringify(data),
      retry: true,
    });
  },
};

// The instructions Review: suggested changes to the custom instructions and
// the memories on their border, accepted or rejected one by one
const INSTRUCTIONS_REVIEW_URL = "/api/users/me/instructions-review";

export const instructionsReview = {
  async review(): Promise<SetupSuggestion[]> {
    try {
      const data = await retryDropped(() =>
        request<SetupReviewResponse>(INSTRUCTIONS_REVIEW_URL, {
          method: "POST",
          // One model call that can take most of a minute
          timeout: QUICK_ACTION_REVIEW_TIMEOUT_MS,
        }),
      );
      return data.suggestions;
    } catch (error) {
      throw new Error(reviewErrorText(error), { cause: error });
    }
  },

  /** Apply one accepted suggestion; resolves to the instructions as they now are. */
  async apply(suggestion: SetupSuggestion): Promise<string> {
    try {
      const data = await request<InstructionsChangeResponse>(`${INSTRUCTIONS_REVIEW_URL}/apply`, {
        method: "POST",
        body: JSON.stringify({
          change: suggestion.change,
          summary: suggestion.summary,
          evidence: suggestion.evidence,
        }),
      });
      return data.custom_instructions;
    } catch (error) {
      throw refreshedOr(error);
    }
  },

  async reject(suggestion: SetupSuggestion): Promise<void> {
    await request<unknown>(`${INSTRUCTIONS_REVIEW_URL}/reject`, {
      method: "POST",
      body: JSON.stringify({ change: suggestion.change, summary: suggestion.summary }),
    });
  },
};
