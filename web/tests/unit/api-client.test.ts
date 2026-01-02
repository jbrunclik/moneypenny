/**
 * Unit tests for API client
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { auth, conversations, chat, models, config, files, costs, ApiError } from '@/api/client';

// Create a mock localStorage
const mockStorage: Record<string, string> = {};
const mockLocalStorage = {
  getItem: vi.fn((key: string) => mockStorage[key] ?? null),
  setItem: vi.fn((key: string, value: string) => {
    mockStorage[key] = value;
  }),
  removeItem: vi.fn((key: string) => {
    delete mockStorage[key];
  }),
  clear: vi.fn(() => {
    Object.keys(mockStorage).forEach((key) => delete mockStorage[key]);
  }),
  key: vi.fn((index: number) => Object.keys(mockStorage)[index] ?? null),
  get length() {
    return Object.keys(mockStorage).length;
  },
};

// Install mock localStorage
Object.defineProperty(global, 'localStorage', {
  value: mockLocalStorage,
  writable: true,
});

// Helper to create mock fetch responses
function mockFetchResponse(data: unknown, status = 200) {
  return vi.fn().mockResolvedValue({
    ok: status >= 200 && status < 300,
    status,
    json: async () => data,
    blob: async () => new Blob([JSON.stringify(data)]),
    body: null,
  });
}

// Helper to create streaming response
function mockStreamResponse(events: Array<{ type: string; [key: string]: unknown }>) {
  const encoder = new TextEncoder();
  const chunks = events.map((e) => `data: ${JSON.stringify(e)}\n\n`).join('');

  return vi.fn().mockResolvedValue({
    ok: true,
    status: 200,
    body: {
      getReader: () => {
        let done = false;
        return {
          read: async () => {
            if (done) {
              return { done: true, value: undefined };
            }
            done = true;
            return { done: false, value: encoder.encode(chunks) };
          },
        };
      },
    },
  });
}

// Helper to clear localStorage (jsdom might not have clear method)
function clearLocalStorage() {
  if (typeof localStorage.clear === 'function') {
    localStorage.clear();
  } else {
    Object.keys(localStorage).forEach((key) => localStorage.removeItem(key));
  }
}

describe('API Client', () => {
  beforeEach(() => {
    // Clear localStorage
    clearLocalStorage();

    // Setup token in Zustand format
    localStorage.setItem(
      'ai-chatbot-storage',
      JSON.stringify({ state: { token: 'test-token' } })
    );
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  describe('auth', () => {
    describe('getClientId', () => {
      it('returns client ID', async () => {
        global.fetch = mockFetchResponse({ client_id: 'google-client-123' });

        const result = await auth.getClientId();

        expect(result).toBe('google-client-123');
        expect(fetch).toHaveBeenCalledWith('/auth/client-id', expect.any(Object));
      });
    });

    describe('googleLogin', () => {
      it('sends credential and returns auth response', async () => {
        const authResponse = { token: 'jwt-token', user: { id: '1', email: 'test@test.com' } };
        global.fetch = mockFetchResponse(authResponse);

        const result = await auth.googleLogin('google-credential');

        expect(result).toEqual(authResponse);
        expect(fetch).toHaveBeenCalledWith(
          '/auth/google',
          expect.objectContaining({
            method: 'POST',
            body: JSON.stringify({ credential: 'google-credential' }),
          })
        );
      });
    });

    describe('me', () => {
      it('returns current user', async () => {
        const user = { id: '1', email: 'test@test.com', name: 'Test', picture: null };
        global.fetch = mockFetchResponse({ user });

        const result = await auth.me();

        expect(result).toEqual(user);
      });
    });
  });

  describe('conversations', () => {
    describe('list', () => {
      it('returns conversation list with pagination', async () => {
        const convs = [
          { id: '1', title: 'First', model: 'gemini', created_at: '', updated_at: '' },
          { id: '2', title: 'Second', model: 'gemini', created_at: '', updated_at: '' },
        ];
        const pagination = { next_cursor: null, has_more: false, total_count: 2 };
        global.fetch = mockFetchResponse({ conversations: convs, pagination });

        const result = await conversations.list();

        expect(result.conversations).toHaveLength(2);
        expect(result.conversations[0].title).toBe('First');
        expect(result.pagination.total_count).toBe(2);
        expect(result.pagination.has_more).toBe(false);
      });

      it('includes auth header', async () => {
        global.fetch = mockFetchResponse({ conversations: [], pagination: { next_cursor: null, has_more: false, total_count: 0 } });

        await conversations.list();

        expect(fetch).toHaveBeenCalledWith(
          '/api/conversations',
          expect.objectContaining({
            headers: expect.objectContaining({
              Authorization: 'Bearer test-token',
            }),
          })
        );
      });

      it('passes pagination parameters', async () => {
        global.fetch = mockFetchResponse({ conversations: [], pagination: { next_cursor: null, has_more: false, total_count: 0 } });

        await conversations.list(20, 'cursor-abc');

        expect(fetch).toHaveBeenCalledWith(
          '/api/conversations?limit=20&cursor=cursor-abc',
          expect.any(Object)
        );
      });
    });

    describe('get', () => {
      it('returns conversation by ID', async () => {
        const conv = { id: '1', title: 'Test', model: 'gemini', created_at: '', updated_at: '' };
        global.fetch = mockFetchResponse(conv);

        const result = await conversations.get('1');

        expect(result).toEqual(conv);
        expect(fetch).toHaveBeenCalledWith('/api/conversations/1', expect.any(Object));
      });
    });

    describe('create', () => {
      it('creates new conversation', async () => {
        const conv = { id: '1', title: 'New', model: 'gemini', created_at: '', updated_at: '' };
        global.fetch = mockFetchResponse(conv);

        const result = await conversations.create('gemini');

        expect(result).toEqual(conv);
        expect(fetch).toHaveBeenCalledWith(
          '/api/conversations',
          expect.objectContaining({
            method: 'POST',
            body: JSON.stringify({ model: 'gemini' }),
          })
        );
      });
    });

    describe('update', () => {
      it('updates conversation', async () => {
        global.fetch = mockFetchResponse({ status: 'ok' });

        await conversations.update('1', { title: 'Updated' });

        expect(fetch).toHaveBeenCalledWith(
          '/api/conversations/1',
          expect.objectContaining({
            method: 'PATCH',
            body: JSON.stringify({ title: 'Updated' }),
          })
        );
      });
    });

    describe('delete', () => {
      it('deletes conversation', async () => {
        global.fetch = mockFetchResponse({ status: 'ok' });

        await conversations.delete('1');

        expect(fetch).toHaveBeenCalledWith(
          '/api/conversations/1',
          expect.objectContaining({
            method: 'DELETE',
          })
        );
      });
    });
  });

  describe('chat', () => {
    describe('sendBatch', () => {
      it('sends message and returns response', async () => {
        const response = {
          id: 'msg-1',
          content: 'Hello!',
          created_at: '2024-01-01',
        };
        global.fetch = mockFetchResponse(response);

        const result = await chat.sendBatch('conv-1', 'Hi there');

        expect(result).toEqual(response);
        expect(fetch).toHaveBeenCalledWith(
          '/api/conversations/conv-1/chat/batch',
          expect.objectContaining({
            method: 'POST',
            body: JSON.stringify({ message: 'Hi there' }),
          })
        );
      });

      it('includes files when provided', async () => {
        global.fetch = mockFetchResponse({ id: '1', content: 'Response', created_at: '' });

        const files = [{ name: 'test.png', type: 'image/png', data: 'base64' }];
        await chat.sendBatch('conv-1', 'Check this', files);

        expect(fetch).toHaveBeenCalledWith(
          '/api/conversations/conv-1/chat/batch',
          expect.objectContaining({
            body: JSON.stringify({ message: 'Check this', files }),
          })
        );
      });

      it('includes force_tools when provided', async () => {
        global.fetch = mockFetchResponse({ id: '1', content: 'Response', created_at: '' });

        await chat.sendBatch('conv-1', 'Search for this', undefined, ['web_search']);

        expect(fetch).toHaveBeenCalledWith(
          '/api/conversations/conv-1/chat/batch',
          expect.objectContaining({
            body: JSON.stringify({ message: 'Search for this', force_tools: ['web_search'] }),
          })
        );
      });
    });

    describe('stream', () => {
      it('yields stream events', async () => {
        const events = [
          { type: 'token', text: 'Hello' },
          { type: 'token', text: ' world' },
          { type: 'done', id: '1', created_at: '2024-01-01' },
        ];
        global.fetch = mockStreamResponse(events);

        const collected = [];
        for await (const event of chat.stream('conv-1', 'Hi')) {
          collected.push(event);
        }

        expect(collected).toHaveLength(3);
        expect(collected[0]).toEqual({ type: 'token', text: 'Hello' });
        expect(collected[2].type).toBe('done');
      });

      it('throws ApiError on non-ok response', async () => {
        global.fetch = vi.fn().mockResolvedValue({
          ok: false,
          status: 401,
          json: async () => ({ error: 'Unauthorized' }),
        });

        const generator = chat.stream('conv-1', 'Hi');

        await expect(generator.next()).rejects.toThrow(ApiError);
      });

      it('throws ApiError with TIMEOUT code when initial fetch is aborted', async () => {
        // Test that AbortError from fetch is converted to ApiError with TIMEOUT code
        global.fetch = vi.fn().mockImplementation(() => {
          const error = new Error('The operation was aborted');
          error.name = 'AbortError';
          return Promise.reject(error);
        });

        const generator = chat.stream('conv-1', 'Hi');

        try {
          await generator.next();
          expect.fail('Should have thrown');
        } catch (e) {
          expect(e).toBeInstanceOf(ApiError);
          expect((e as ApiError).code).toBe('TIMEOUT');
          expect((e as ApiError).isTimeout).toBe(true);
          expect((e as ApiError).message).toContain('timed out');
        }
      });

      it('throws ApiError with TIMEOUT code when stream read times out', async () => {
        vi.useFakeTimers();

        // Create a mock reader with proper cancel method
        const mockCancel = vi.fn().mockResolvedValue(undefined);

        // Mock a response where reader.read() never resolves (simulating dropped connection)
        global.fetch = vi.fn().mockResolvedValue({
          ok: true,
          status: 200,
          body: {
            getReader: () => ({
              read: () =>
                new Promise(() => {
                  // Never resolves - simulates connection drop
                }),
              cancel: mockCancel,
            }),
          },
        });

        const generator = chat.stream('conv-1', 'Hi');
        const nextPromise = generator.next();

        // Advance past the STREAM_READ_TIMEOUT (60 seconds)
        await vi.advanceTimersByTimeAsync(60001);

        // Should yield an error event first, then throw
        const result = await nextPromise;
        expect(result.value).toEqual(
          expect.objectContaining({
            type: 'error',
            code: 'TIMEOUT',
          })
        );

        // Verify reader.cancel() was called
        expect(mockCancel).toHaveBeenCalled();

        // Next iteration should throw
        await expect(generator.next()).rejects.toThrow(ApiError);

        vi.useRealTimers();
      });

      it('yields error event before throwing on stream timeout', async () => {
        vi.useFakeTimers();

        const mockCancel = vi.fn().mockResolvedValue(undefined);

        global.fetch = vi.fn().mockResolvedValue({
          ok: true,
          status: 200,
          body: {
            getReader: () => ({
              read: () => new Promise(() => {}), // Never resolves
              cancel: mockCancel,
            }),
          },
        });

        const generator = chat.stream('conv-1', 'Hi');
        const nextPromise = generator.next();

        await vi.advanceTimersByTimeAsync(60001);

        // First should yield error event
        const errorEvent = await nextPromise;
        expect(errorEvent.value?.type).toBe('error');
        expect(errorEvent.value?.code).toBe('TIMEOUT');
        expect(errorEvent.value?.retryable).toBe(false);
        expect(errorEvent.done).toBe(false);

        vi.useRealTimers();
      });

      it('handles successful read after timeout is set but before it fires', async () => {
        // This tests the race condition fix - if read() resolves quickly,
        // the timeout should be cleared and not cause issues
        const events = [
          { type: 'token', text: 'Quick response' },
          { type: 'done', id: '1', created_at: '2024-01-01' },
        ];
        global.fetch = mockStreamResponse(events);

        const collected = [];
        for await (const event of chat.stream('conv-1', 'Hi')) {
          collected.push(event);
        }

        // Should complete normally without timeout interference
        expect(collected).toHaveLength(2);
        expect(collected[0].type).toBe('token');
        expect(collected[1].type).toBe('done');
      });

      it('includes force_tools in stream request', async () => {
        const events = [{ type: 'done', id: '1', created_at: '2024-01-01' }];
        global.fetch = mockStreamResponse(events);

        const collected = [];
        for await (const event of chat.stream('conv-1', 'Search this', undefined, ['web_search'])) {
          collected.push(event);
        }

        expect(fetch).toHaveBeenCalledWith(
          '/api/conversations/conv-1/chat/stream',
          expect.objectContaining({
            body: JSON.stringify({
              message: 'Search this',
              force_tools: ['web_search'],
            }),
          })
        );
      });
    });
  });

  describe('models', () => {
    describe('list', () => {
      it('returns models and default', async () => {
        const response = {
          models: [{ id: 'model-1', name: 'Model 1' }],
          default: 'model-1',
        };
        global.fetch = mockFetchResponse(response);

        const result = await models.list();

        expect(result.models).toHaveLength(1);
        expect(result.default).toBe('model-1');
      });
    });
  });

  describe('config', () => {
    describe('getUploadConfig', () => {
      it('returns upload config', async () => {
        const uploadConfig = {
          maxFileSize: 20 * 1024 * 1024,
          maxFilesPerMessage: 10,
          allowedFileTypes: ['image/png'],
        };
        global.fetch = mockFetchResponse(uploadConfig);

        const result = await config.getUploadConfig();

        expect(result).toEqual(uploadConfig);
      });
    });
  });

  describe('files', () => {
    describe('getThumbnailUrl', () => {
      it('returns correct URL', () => {
        const url = files.getThumbnailUrl('msg-123', 0);
        expect(url).toBe('/api/messages/msg-123/files/0/thumbnail');
      });
    });

    describe('getFileUrl', () => {
      it('returns correct URL', () => {
        const url = files.getFileUrl('msg-123', 2);
        expect(url).toBe('/api/messages/msg-123/files/2');
      });
    });

    describe('fetchThumbnail', () => {
      it('fetches and returns blob', async () => {
        const blob = new Blob(['image data'], { type: 'image/png' });
        global.fetch = vi.fn().mockResolvedValue({
          ok: true,
          blob: async () => blob,
        });

        const result = await files.fetchThumbnail('msg-1', 0);

        expect(result).toBeInstanceOf(Blob);
      });

      it('throws on error', async () => {
        global.fetch = vi.fn().mockResolvedValue({
          ok: false,
          status: 404,
        });

        await expect(files.fetchThumbnail('msg-1', 0)).rejects.toThrow(ApiError);
      });
    });
  });

  describe('costs', () => {
    describe('getConversationCost', () => {
      it('returns conversation cost', async () => {
        const costResponse = { cost: 0.05, currency: 'CZK' };
        global.fetch = mockFetchResponse(costResponse);

        const result = await costs.getConversationCost('conv-1');

        expect(result).toEqual(costResponse);
      });
    });

    describe('getMonthlyCost', () => {
      it('returns monthly cost without params', async () => {
        const costResponse = { cost: 10.5, currency: 'CZK' };
        global.fetch = mockFetchResponse(costResponse);

        await costs.getMonthlyCost();

        expect(fetch).toHaveBeenCalledWith(
          '/api/users/me/costs/monthly',
          expect.any(Object)
        );
      });

      it('includes year and month params', async () => {
        global.fetch = mockFetchResponse({ cost: 10.5, currency: 'CZK' });

        await costs.getMonthlyCost(2024, 6);

        expect(fetch).toHaveBeenCalledWith(
          '/api/users/me/costs/monthly?year=2024&month=6',
          expect.any(Object)
        );
      });
    });

    describe('getCostHistory', () => {
      it('returns cost history', async () => {
        const history = { months: [], currency: 'CZK' };
        global.fetch = mockFetchResponse(history);

        await costs.getCostHistory(12);

        expect(fetch).toHaveBeenCalledWith(
          '/api/users/me/costs/history?limit=12',
          expect.any(Object)
        );
      });
    });

    describe('getMessageCost', () => {
      it('returns message cost', async () => {
        const costResponse = {
          input_tokens: 100,
          output_tokens: 50,
          cost: 0.01,
          currency: 'CZK',
        };
        global.fetch = mockFetchResponse(costResponse);

        const result = await costs.getMessageCost('msg-1');

        expect(result).toEqual(costResponse);
      });
    });
  });

  describe('Error handling', () => {
    it('throws ApiError on failed requests', async () => {
      global.fetch = mockFetchResponse({ error: 'Not found' }, 404);

      await expect(conversations.get('nonexistent')).rejects.toThrow(ApiError);
    });

    it('includes status code in ApiError', async () => {
      // Backend returns structured error format: { error: { code, message } }
      global.fetch = mockFetchResponse({ error: { code: 'FORBIDDEN', message: 'Forbidden' } }, 403);

      try {
        await conversations.list();
        expect.fail('Should have thrown');
      } catch (e) {
        expect(e).toBeInstanceOf(ApiError);
        expect((e as ApiError).status).toBe(403);
        expect((e as ApiError).message).toBe('Forbidden');
      }
    });

    it('detects AUTH_EXPIRED error code', async () => {
      global.fetch = mockFetchResponse(
        { error: { code: 'AUTH_EXPIRED', message: 'Token expired' } },
        401
      );

      try {
        await auth.me();
        expect.fail('Should have thrown');
      } catch (e) {
        expect(e).toBeInstanceOf(ApiError);
        expect((e as ApiError).isTokenExpired).toBe(true);
        expect((e as ApiError).isAuthError).toBe(true);
        expect((e as ApiError).code).toBe('AUTH_EXPIRED');
      }
    });

    it('detects AUTH_INVALID error code', async () => {
      global.fetch = mockFetchResponse(
        { error: { code: 'AUTH_INVALID', message: 'Invalid token' } },
        401
      );

      try {
        await auth.me();
        expect.fail('Should have thrown');
      } catch (e) {
        expect(e).toBeInstanceOf(ApiError);
        expect((e as ApiError).isTokenExpired).toBe(false);
        expect((e as ApiError).isAuthError).toBe(true);
        expect((e as ApiError).code).toBe('AUTH_INVALID');
      }
    });

    it('detects AUTH_REQUIRED error code', async () => {
      global.fetch = mockFetchResponse(
        { error: { code: 'AUTH_REQUIRED', message: 'Authentication required' } },
        401
      );

      try {
        await auth.me();
        expect.fail('Should have thrown');
      } catch (e) {
        expect(e).toBeInstanceOf(ApiError);
        expect((e as ApiError).isAuthError).toBe(true);
        expect((e as ApiError).code).toBe('AUTH_REQUIRED');
      }
    });

    it('detects 401 status as auth error', async () => {
      // Even without specific code, 401 should be detected as auth error
      global.fetch = mockFetchResponse({ error: 'Unauthorized' }, 401);

      try {
        await auth.me();
        expect.fail('Should have thrown');
      } catch (e) {
        expect(e).toBeInstanceOf(ApiError);
        expect((e as ApiError).isAuthError).toBe(true);
        expect((e as ApiError).status).toBe(401);
      }
    });
  });

  describe('auth.refreshToken', () => {
    it('refreshes token and returns new token', async () => {
      global.fetch = mockFetchResponse({ token: 'new-jwt-token' });

      const result = await auth.refreshToken();

      expect(result).toBe('new-jwt-token');
      expect(fetch).toHaveBeenCalledWith(
        '/auth/refresh',
        expect.objectContaining({
          method: 'POST',
          headers: expect.objectContaining({
            Authorization: 'Bearer test-token',
          }),
        })
      );
    });

    it('throws ApiError on expired token', async () => {
      global.fetch = mockFetchResponse(
        { error: { code: 'AUTH_EXPIRED', message: 'Token expired' } },
        401
      );

      try {
        await auth.refreshToken();
        expect.fail('Should have thrown');
      } catch (e) {
        expect(e).toBeInstanceOf(ApiError);
        expect((e as ApiError).isTokenExpired).toBe(true);
      }
    });
  });

  describe('Token handling', () => {
    it('uses token from Zustand storage', async () => {
      localStorage.setItem(
        'ai-chatbot-storage',
        JSON.stringify({ state: { token: 'zustand-token' } })
      );
      global.fetch = mockFetchResponse({ conversations: [] });

      await conversations.list();

      expect(fetch).toHaveBeenCalledWith(
        expect.any(String),
        expect.objectContaining({
          headers: expect.objectContaining({
            Authorization: 'Bearer zustand-token',
          }),
        })
      );
    });

    it('falls back to legacy token storage', async () => {
      clearLocalStorage();
      localStorage.setItem('token', 'legacy-token');
      global.fetch = mockFetchResponse({ conversations: [] });

      await conversations.list();

      expect(fetch).toHaveBeenCalledWith(
        expect.any(String),
        expect.objectContaining({
          headers: expect.objectContaining({
            Authorization: 'Bearer legacy-token',
          }),
        })
      );
    });

    it('works without token', async () => {
      clearLocalStorage();
      global.fetch = mockFetchResponse({ conversations: [] });

      await conversations.list();

      expect(fetch).toHaveBeenCalledWith(
        expect.any(String),
        expect.objectContaining({
          headers: expect.not.objectContaining({
            Authorization: expect.any(String),
          }),
        })
      );
    });
  });
});
