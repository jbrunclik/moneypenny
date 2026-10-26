/**
 * tryResumeStream when a resume attempt fails: no journal (404) falls back
 * to poll recovery at once, a user stop propagates, a proactive foreground
 * abort retries immediately, other errors back off and retry.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

const resumeStream = vi.hoisted(() => vi.fn());

vi.mock('@/components/messages', () => ({
  addStreamingMessage: vi.fn(),
  getStreamingMessageElement: vi.fn(() => null),
  cleanupStreamingContext: vi.fn(),
}));
vi.mock('@/components/Toast', () => ({ toast: { info: vi.fn(), warning: vi.fn(), error: vi.fn() } }));
vi.mock('@/components/MessageInput', () => ({ hideUploadProgress: vi.fn(), showUploadProgress: vi.fn() }));
vi.mock('@/core/stream-recovery', () => ({
  markStreamForRecovery: vi.fn(),
  clearPendingRecovery: vi.fn(),
  attemptRecovery: vi.fn(async () => false),
}));
vi.mock('@/api/chat', () => ({ chat: { resumeStream } }));

import { ApiError } from '@/api/http';
import { createStreamingState } from '@/core/stream-session';
import { tryResumeStream } from '@/core/stream-resume';

function makeState() {
  const el = document.createElement('div');
  document.body.appendChild(el);
  return createStreamingState(el, {
    expectedAssistantMessageId: 'm1',
    activeAbortController: new AbortController(),
  });
}

const abortError = () => Object.assign(new Error('Aborted'), { name: 'AbortError' });

function failingResume(error: unknown) {
  // eslint-disable-next-line require-yield
  return async function* () {
    throw error;
  };
}

describe('tryResumeStream error outcomes', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.useFakeTimers();
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it('falls back right away when the server has no journal (404)', async () => {
    resumeStream.mockImplementation(failingResume(new ApiError('Not found', 404)));

    await expect(tryResumeStream(makeState(), 'c1', 'temp-1')).resolves.toBe(false);
    expect(resumeStream).toHaveBeenCalledTimes(1);
  });

  it('propagates a user-initiated stop', async () => {
    resumeStream.mockImplementation(failingResume(abortError()));

    await expect(tryResumeStream(makeState(), 'c1', 'temp-1')).rejects.toMatchObject({ name: 'AbortError' });
    expect(resumeStream).toHaveBeenCalledTimes(1);
  });

  it('retries immediately after a proactive foreground abort', async () => {
    const state = makeState();
    resumeStream
      .mockImplementationOnce(() => {
        state.resumeViaAbort = true;
        return failingResume(abortError())();
      })
      .mockImplementation(failingResume(new ApiError('Not found', 404)));

    await expect(tryResumeStream(state, 'c1', 'temp-1')).resolves.toBe(false);
    expect(resumeStream).toHaveBeenCalledTimes(2);
  });

  it('backs off and retries after another error', async () => {
    resumeStream
      .mockImplementationOnce(failingResume(new Error('reset')))
      .mockImplementation(failingResume(new ApiError('Not found', 404)));

    const pending = tryResumeStream(makeState(), 'c1', 'temp-1');
    await vi.advanceTimersByTimeAsync(1000);

    await expect(pending).resolves.toBe(false);
    expect(resumeStream).toHaveBeenCalledTimes(2);
  });
});
