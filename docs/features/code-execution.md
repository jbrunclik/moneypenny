# Code Execution Sandbox

The app can execute Python code in a secure Docker sandbox using [llm-sandbox](https://github.com/vndee/llm-sandbox).

## How it works

1. **Tool available**: `execute_code(code)` tool in [tools/code_execution.py](../../src/agent/tools/code_execution.py)
2. **Docker sandbox**: Code runs in an isolated container with no network access
3. **Custom image**: Uses a pre-built Docker image with fonts and libraries pre-installed for faster execution
4. **File output**: Code saves files to `/output/` directory, which are extracted and returned
5. **Automatic plots**: Matplotlib plots are captured automatically via llm-sandbox
6. **Pre-installed libraries**: numpy, pandas, matplotlib, scipy, sympy, pillow, reportlab, fpdf2

## Custom Docker Image

For optimal performance, the app uses a custom Docker image with pre-installed dependencies:

**Building the image:**
```bash
make sandbox-image
```

This builds `moneypenny-sandbox:local` with:
- DejaVu fonts for Unicode support in PDF generation (fpdf2)
- All Python libraries pre-installed (numpy, pandas, matplotlib, etc.)
- Compiler tools (gcc, g++) for native extensions

**Benefits:**
- **Faster execution**: No runtime font installation (~2-5s saved per fpdf execution)
- **Faster library loading**: Pre-installed libraries avoid pip install overhead
- **Reliability**: No risk of apt-get or pip failures during execution

**Automatic cleanup:**
- `make sandbox-image` removes old image versions to prevent bloat
- Each build replaces the previous `moneypenny-sandbox:local` image

## Security Constraints

- **No network**: Containers run with `--network none` (default in llm-sandbox)
- **No host access**: Code cannot access files outside the container
- **Resource limits**: Configurable timeout (30s default), memory limit (512MB default)
- **Per-conversation sessions**: Containers are reused across `execute_code`
  calls within a conversation ([sandbox_sessions.py](../../src/agent/tools/sandbox_sessions.py):
  LRU pool, `CODE_SANDBOX_MAX_SESSIONS` per worker, idle TTL
  `CODE_SANDBOX_SESSION_TTL_SECONDS`). Files in `/work/` persist across calls;
  variables do NOT (each run is a fresh Python process); `/output/` is cleared
  at the start of every run. Without a conversation context the session is
  ephemeral (created and destroyed per call, the old behavior).

## Configuration

```bash
CODE_SANDBOX_ENABLED=true                    # Enable/disable (default: true)
CODE_SANDBOX_IMAGE=moneypenny-sandbox:local  # Custom Docker image (required)
CODE_SANDBOX_TIMEOUT=30                      # Execution timeout in seconds
CODE_SANDBOX_MEMORY_LIMIT=512m               # Container memory limit
CODE_SANDBOX_CPU_LIMIT=1.0                   # CPU limit (1.0 = 1 core)
CODE_SANDBOX_MAX_SESSIONS=2                  # Pooled sessions per worker
CODE_SANDBOX_SESSION_TTL_SECONDS=900         # Idle session lifetime
```

The sandbox container runs with **networking disabled** and the memory/CPU
limits above. Available Python libraries are baked into the Docker image
([docker/code-sandbox/Dockerfile](../../docker/code-sandbox/Dockerfile)) -
runtime installation is not possible without network. To add a library, add it
to the Dockerfile and rebuild with `make sandbox-image`.

## Deployment

Each deployment environment must build the custom image:

```bash
# Initial setup
make setup
make sandbox-image

# Update .env
CODE_SANDBOX_IMAGE=moneypenny-sandbox:local

# On updates (if Dockerfile changed)
make sandbox-image
```

**Note:** The custom image is required. The base Python image lacks pre-installed fonts and libraries, causing code execution to fail or perform poorly.

## File Output Pattern (uses `_full_result` to save tokens)

The tool uses the same `_full_result` pattern as `generate_image` to avoid sending large file data back to the LLM:

1. **Wrapped execution**: User code is wrapped to create `/output/` directory and list files after execution
2. **File extraction**: Files are extracted via `session.copy_from_runtime()` to temp files
3. **LLM sees metadata only**: Response includes file metadata (name, type, size) but NOT the base64 data
4. **Full data in `_full_result`**: Actual file data is stored in `_full_result.files` for server-side extraction
5. **Server extracts files**: `extract_code_output_files_from_tool_results()` extracts files from `_full_result`
6. **Stored as attachments**: Files are attached to the assistant message like any other file upload

**Token optimization:**
- Without this pattern: Each 100KB file would add ~130K tokens to the next request
- With this pattern: LLM only sees ~50 tokens of metadata per file

## Example Use Cases

- Mathematical calculations (sympy for symbolic math)
- Data analysis (pandas, numpy)
- Charts and visualizations (matplotlib)
- PDF document generation (reportlab)
- JSON/CSV data transformation

## Graceful Degradation

- If Docker is not available, the tool returns an error message
- Docker availability is checked once and cached
- The tool is only added to the available tools list if `CODE_SANDBOX_ENABLED=true` (`is_code_sandbox_available()` additionally checks Docker)

## Key Files

- [code_execution.py](../../src/agent/tools/code_execution.py) - `execute_code()` tool, `is_code_sandbox_available()`, `_check_docker_available()`
- [Dockerfile](../../docker/code-sandbox/Dockerfile) - Custom Docker image with pre-installed fonts and libraries
- [Makefile](../../Makefile) - `sandbox-image` target for building custom image
- [images.py](../../src/utils/images.py) - `extract_code_output_files_from_tool_results()` for file extraction
- [config.py](../../src/config.py) - `CODE_SANDBOX_*` configuration options
- [prompt_texts/core.py](../../src/agent/prompt_texts/core.py) - System prompt with code execution instructions
- [chat_save.py](../../src/api/helpers/chat_save.py) - extracts and attaches code output files when the turn is saved
- [sandbox_sessions.py](../../src/agent/tools/sandbox_sessions.py) - per-conversation session pool

## Testing Locally

```bash
# Ensure Docker is running
docker info

# Test the sandbox manually
python -c "
from llm_sandbox import SandboxSession
with SandboxSession(lang='python') as s:
    result = s.run('print(1+1)')
    print(result.stdout)
"
```

## Testing

- Unit: [test_sandbox_sessions.py](../../tests/unit/test_sandbox_sessions.py), `execute_code` cases in [test_tools.py](../../tests/unit/test_tools.py)
- Integration: [test_code_sandbox_isolation.py](../../tests/integration/test_code_sandbox_isolation.py) (needs Docker)

## See Also

- [Setup](../setup.md) - installing Docker and building the sandbox image
- [Agent Graph](../architecture/agent-graph.md#tool-node) - the `_full_result` capture/strip step
- [Image Generation](image-generation.md) - the other tool that returns files
