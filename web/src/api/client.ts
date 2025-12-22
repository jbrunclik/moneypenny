import type {
  AuthResponse,
  ChatResponse,
  Conversation,
  ConversationsResponse,
  DetailEvent,
  ErrorResponse,
  FileUpload,
  ModelsResponse,
  StreamEvent,
  UploadConfig,
  User,
} from '../types/api';

class ApiError extends Error {
  constructor(
    message: string,
    public status: number
  ) {
    super(message);
    this.name = 'ApiError';
  }
}

type ApiResponse<T> = T | ErrorResponse;

function getToken(): string | null {
  // Try Zustand persisted store first
  const stored = localStorage.getItem('ai-chatbot-storage');
  if (stored) {
    try {
      const parsed = JSON.parse(stored);
      if (parsed.state?.token) {
        return parsed.state.token;
      }
    } catch {
      // Ignore parse errors
    }
  }
  // Fallback to legacy direct token storage
  return localStorage.getItem('token');
}

async function request<T>(
  url: string,
  options: RequestInit = {}
): Promise<T> {
  const token = getToken();

  const headers: HeadersInit = {
    'Content-Type': 'application/json',
    ...options.headers,
  };

  if (token) {
    (headers as Record<string, string>)['Authorization'] = `Bearer ${token}`;
  }

  const response = await fetch(url, {
    ...options,
    headers,
  });

  const data = (await response.json()) as ApiResponse<T>;

  if (!response.ok) {
    const error = (data as ErrorResponse).error || 'Request failed';
    throw new ApiError(error, response.status);
  }

  return data as T;
}

// Auth endpoints
export const auth = {
  async getClientId(): Promise<string> {
    const data = await request<{ client_id: string }>('/auth/client-id');
    return data.client_id;
  },

  async googleLogin(credential: string): Promise<AuthResponse> {
    return request<AuthResponse>('/auth/google', {
      method: 'POST',
      body: JSON.stringify({ credential }),
    });
  },

  async me(): Promise<User> {
    const data = await request<{ user: User }>('/auth/me');
    return data.user;
  },
};

// Conversation endpoints
export const conversations = {
  async list(): Promise<Conversation[]> {
    const data = await request<ConversationsResponse>('/api/conversations');
    return data.conversations;
  },

  async get(id: string): Promise<Conversation> {
    return request<Conversation>(`/api/conversations/${id}`);
  },

  async create(model?: string): Promise<Conversation> {
    return request<Conversation>('/api/conversations', {
      method: 'POST',
      body: JSON.stringify({ model }),
    });
  },

  async update(
    id: string,
    data: { title?: string; model?: string }
  ): Promise<void> {
    await request<{ status: string }>(`/api/conversations/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(data),
    });
  },

  async delete(id: string): Promise<void> {
    await request<{ status: string }>(`/api/conversations/${id}`, {
      method: 'DELETE',
    });
  },
};

// Chat endpoints
export const chat = {
  async sendBatch(
    conversationId: string,
    message: string,
    files?: FileUpload[],
    forceTools?: string[]
  ): Promise<ChatResponse> {
    return request<ChatResponse>(
      `/api/conversations/${conversationId}/chat/batch`,
      {
        method: 'POST',
        body: JSON.stringify({
          message,
          files,
          force_tools: forceTools?.length ? forceTools : undefined,
        }),
      }
    );
  },

  async *stream(
    conversationId: string,
    message: string,
    files?: FileUpload[],
    forceTools?: string[]
  ): AsyncGenerator<StreamEvent> {
    const token = getToken();

    const response = await fetch(
      `/api/conversations/${conversationId}/chat/stream`,
      {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify({
          message,
          files,
          force_tools: forceTools?.length ? forceTools : undefined,
        }),
      }
    );

    if (!response.ok) {
      const data = (await response.json()) as ErrorResponse;
      throw new ApiError(data.error || 'Stream request failed', response.status);
    }

    const reader = response.body?.getReader();
    if (!reader) {
      throw new Error('No response body');
    }

    const decoder = new TextDecoder();
    let buffer = '';

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n');
      buffer = lines.pop() || '';

      for (const line of lines) {
        if (line.startsWith('data: ')) {
          const data = line.slice(6);
          try {
            yield JSON.parse(data) as StreamEvent;
          } catch {
            // Ignore invalid JSON
          }
        }
      }
    }
  },
};

// Models endpoint
export const models = {
  async list(): Promise<ModelsResponse> {
    return request<ModelsResponse>('/api/models');
  },
};

// Config endpoint
export const config = {
  async getUploadConfig(): Promise<UploadConfig> {
    return request<UploadConfig>('/api/config/upload');
  },
};

// File endpoints
export const files = {
  getThumbnailUrl(messageId: string, fileIndex: number): string {
    return `/api/messages/${messageId}/files/${fileIndex}/thumbnail`;
  },

  getFileUrl(messageId: string, fileIndex: number): string {
    return `/api/messages/${messageId}/files/${fileIndex}`;
  },

  async fetchThumbnail(messageId: string, fileIndex: number): Promise<Blob> {
    const token = getToken();
    const response = await fetch(
      `/api/messages/${messageId}/files/${fileIndex}/thumbnail`,
      {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      }
    );

    if (!response.ok) {
      throw new ApiError('Failed to fetch thumbnail', response.status);
    }

    return response.blob();
  },

  async fetchFile(messageId: string, fileIndex: number): Promise<Blob> {
    const token = getToken();
    const response = await fetch(
      `/api/messages/${messageId}/files/${fileIndex}`,
      {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      }
    );

    if (!response.ok) {
      throw new ApiError('Failed to fetch file', response.status);
    }

    return response.blob();
  },
};

// Message endpoints
export const messages = {
  async getDetails(messageId: string): Promise<DetailEvent[]> {
    const data = await request<{ details: DetailEvent[] }>(
      `/api/messages/${messageId}/details`
    );
    return data.details;
  },
};

export { ApiError };