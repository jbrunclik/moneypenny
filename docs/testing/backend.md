# Backend Testing

pytest unit and integration tests for the Flask backend and the agent. Run them with `make test` (see [Testing](../testing.md) for all commands).

## Test Structure

```
tests/
├── conftest.py                    # Shared fixtures (database, app, auth, mocks)
├── fixtures/
│   └── images.py                  # Test image generators
├── mocks/
│   └── gemini.py                  # Mock LLM response builders
├── unit/                          # Unit tests (isolated function testing)
│   ├── test_costs.py              # Cost calculations
│   ├── test_jwt_auth.py           # JWT token handling
│   ├── test_google_auth.py        # Google token verification
│   ├── test_chat_agent_helpers.py # Agent helper functions
│   ├── test_images.py             # Image processing
│   └── test_tools.py              # Agent tools (mocked externals)
├── integration/                   # Integration tests (multi-component)
│   ├── test_db_models.py          # Database CRUD operations
│   ├── test_routes_auth.py        # Auth endpoints
│   ├── test_routes_conversations.py  # Conversation CRUD
│   ├── test_routes_chat.py        # Chat endpoints
│   ├── test_routes_chat_turn.py   # Shared chat turn setup (batch + streaming)
│   └── test_routes_costs.py       # Cost tracking endpoints
└── e2e-server.py                  # Mock Flask server for E2E tests
```

## Key Testing Patterns (Backend)

**Isolated SQLite per test**:
- Each test gets its own database file for complete isolation
- Database fixture creates a fresh database for each test
- No shared state between tests

**Mocked external services**:
- Gemini LLM responses are mocked with proper AIMessage objects
- Google Auth token verification is mocked
- Web search is mocked (`mock_ddgs` patches `src.agent.tools.DDGS`)
- HTTP requests (httpx) are mocked

**Shared fixtures** (from [tests/conftest.py](../../tests/conftest.py)):
```python
def test_example(client, test_user, test_conversation, auth_headers):
    # client: Flask test client
    # test_user: Pre-created user
    # test_conversation: Pre-created conversation for test_user
    # auth_headers: JWT auth headers for test_user
    response = client.get('/api/conversations', headers=auth_headers)
    assert response.status_code == 200
```

**Flask test client**:
```python
def test_endpoint(client, auth_headers):
    response = client.post('/api/endpoint',
                          headers=auth_headers,
                          json={'data': 'value'})
    assert response.status_code == 200
    data = response.get_json()
    assert data['success'] is True
```

## Unit Tests

Unit tests focus on isolated function testing with all dependencies mocked:

```python
# tests/unit/test_costs.py
def test_calculate_cost():
    cost = calculate_token_cost(
        input_tokens=1000,
        output_tokens=500,
        model='gemini-3-flash-preview'
    )
    assert cost > 0
    assert isinstance(cost, float)
```

## Integration Tests

Integration tests verify multiple components working together:

```python
# tests/integration/test_routes_chat.py
def test_chat_endpoint(client, test_user, test_conversation, auth_headers):
    response = client.post(
        '/chat/batch',
        headers=auth_headers,
        json={
            'conversation_id': test_conversation.id,
            'message': 'Hello',
            'stream': False,
        }
    )
    assert response.status_code == 200
    data = response.get_json()
    assert 'response' in data
```

## Mock Return Value Formats (Chat Path)

When mocking the agent's chat entrypoints, the return shapes must match exactly
or downstream code (metadata extraction, cost saving) breaks.

**`ChatAgent.chat_batch`** returns a 4-tuple
`(response_text, tool_results, usage_info, result_messages)`:

```python
mock_chat.return_value = ("Response text", [], usage_info, [ai_message])
```

- `result_messages` is the full list of LangChain `BaseMessage` objects from the
  graph — sources, generated-image prompts, and memory ops are extracted from it.
- `usage_info` is a dict: `input_tokens`, `output_tokens`, `cached_input_tokens`,
  `tool_rounds`, `tool_call_count`.

**`ChatAgent.stream_chat_events`** yields events; the terminal event carries the
same payload under `result_messages` (not `metadata`):

```python
yield {
    "type": "final",
    "content": "...",
    "tool_results": [...],
    "usage_info": {...},
    "result_messages": [ai_message],
}
```

When you change either return type, update **every** mock return value across
`tests/` and `web/tests/` — see the Interface Extension Checklist below.

## Writing New Backend Tests

**1. Unit tests** for pure functions in `tests/unit/`:

```python
# tests/unit/test_mymodule.py
import pytest
from src.mymodule import my_function

def test_my_function():
    result = my_function(input_value)
    assert result == expected_value
```

**2. Integration tests** for API endpoints in `tests/integration/`:

```python
# tests/integration/test_routes_myendpoint.py
def test_my_endpoint(client, auth_headers):
    response = client.get('/api/myendpoint', headers=auth_headers)
    assert response.status_code == 200
```

**3. Use existing fixtures** from conftest.py:

```python
def test_with_fixtures(client, test_user, auth_headers, mock_gemini_llm):
    # test_user: Pre-created user
    # auth_headers: JWT headers for test_user
    # mock_gemini_llm: Mocked LLM responses
    pass
```

**4. Never make real API calls** - mock at the right level:

```python
@pytest.fixture
def mock_external_api(monkeypatch):
    def mock_call(*args, **kwargs):
        return {'status': 'success'}
    monkeypatch.setattr('mymodule.external_api_call', mock_call)
    return mock_call
```

## Planner Tests (backend)

**Unit Tests** ([tests/unit/test_planner.py](../../tests/unit/test_planner.py)):
- Dashboard data formatting
- Date range calculations
- Task priority handling
- Event/task merging logic

**Integration Tests** ([tests/integration/test_routes_planner.py](../../tests/integration/test_routes_planner.py)):
- `GET /api/planner` (dashboard endpoint)
- `GET /api/planner/conversation` (get or create planner conversation)
- `POST /api/planner/reset` (reset conversation)
- Integration error handling
- Dashboard caching

## Key Files

- [tests/conftest.py](../../tests/conftest.py) - shared fixtures (`client`, `test_user`, `test_conversation`, `auth_headers`, `mock_gemini_llm`, `mock_ddgs`)
- [tests/mocks/gemini.py](../../tests/mocks/gemini.py) - mock LLM response builders
- [tests/fixtures/images.py](../../tests/fixtures/images.py) - test image generators

## See Also

- [Testing](../testing.md) - commands, TDD, isolation and mocking rules, lint/coverage gates
- [Frontend and E2E Testing](frontend.md) - Vitest, Playwright and the E2E mock server
- [Evals](evals.md) - agent-behavior evals against the live API
