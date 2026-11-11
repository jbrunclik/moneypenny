/**
 * What the two setup Reviews share at the API edge (the Quick actions sheet's
 * program Review and Settings' instructions Review): one quiet retry after a
 * dropped connection, a collision as the refreshed suggestion, and failures
 * in plain words.
 */
import type { SetupSuggestion } from "../types/api";
import { ApiError } from "./http";

/**
 * Thrown by an apply when what the suggestion touches changed since the review
 * (a collision): it carries the same change against the current state.
 */
export class SuggestionRefreshed extends Error {
  constructor(readonly suggestion: SetupSuggestion) {
    super("This changed since the review.");
    this.name = "SuggestionRefreshed";
  }
}

/**
 * A collision (409 with the refreshed suggestion) as SuggestionRefreshed, so
 * the card shows the updated change; any other error as is.
 */
export function refreshedOr(error: unknown): unknown {
  const fresh =
    error instanceof ApiError && error.status === 409 ? error.details?.suggestion : undefined;
  return fresh && typeof fresh === "object"
    ? new SuggestionRefreshed(fresh as SetupSuggestion)
    : error;
}

/** Why a Review failed, in plain words. */
export function reviewErrorText(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.isTimeout) return "It took too long to answer.";
    if (error.isNetworkError) return "Couldn't reach Moneypenny - check your connection.";
    if (error.message) return error.message;
  }
  return "Something went wrong on our side.";
}

/**
 * Run a Review call, once more if the connection dropped: iOS drops a
 * backgrounded PWA's requests, and the Review only reads (Nov 11 2026: the
 * server answered while the phone had given up).
 */
export async function retryDropped<T>(call: () => Promise<T>): Promise<T> {
  try {
    return await call();
  } catch (error) {
    if (!(error instanceof ApiError && error.isNetworkError)) throw error;
    return call();
  }
}
