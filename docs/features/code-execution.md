# Code Execution Sandbox

The app can execute Python code in a Docker sandbox: one container per conversation session, driven over docker-py by [docker_sandbox.py](../../src/agent/tools/docker_sandbox.py) (llm-sandbox until Nov 16 2026).

## How it works

1. **Tool available**: `execute_code(code)` tool in [tools/code_execution.py](../../src/agent/tools/code_execution.py)
2. **Docker sandbox**: Code runs in an isolated container with no network access
3. **Custom image**: Uses a pre-built Docker image with fonts and libraries pre-installed for faster execution
4. **File output**: Code saves files to `/output/` directory, which are extracted and returned
5. **Plots**: saved with `plt.savefig` into `/output/` like any other file (llm-sandbox's plot capture was never on - its console session has none - and was removed Nov 16 2026)
6. **Pre-installed libraries**: numpy, pandas, matplotlib, scipy, sympy, pillow, reportlab, fpdf2, requests, beautifulsoup4, lxml, openpyxl, python-docx, python-pptx, python-dateutil, pytz

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

- **No network**: containers run with networking disabled
- **Non-root, capped** (Nov 16 2026, [spec](../superpowers/specs/2026-11-16-agent-safety-design.md)):
  code runs as uid 10001 (`sandbox` in the image), `cap_drop` ALL with only KILL
  added (the Stop kill runs as root), `no-new-privileges`, `pids_limit`
  `CODE_SANDBOX_PIDS_LIMIT` (128: a fork bomb stops at ~124).
- **Disk cap**: the root filesystem is read-only; `/work` (`CODE_SANDBOX_WORK_MB`,
  256), `/output` (64m) and `/tmp` (64m) are tmpfs, whose pages count against the
  512 MB memory limit - a full disk fails inside the sandbox (ENOSPC; the result's
  stderr gains a "sandbox disk is full" note), never on the host (ext4 there cannot
  quota a container). `/work` is therefore lost when a container is recreated.
- **Moving files**: Docker's copy can neither see tmpfs nor write a read-only root.
  The app writes code (`code-<n>.py`) and incoming files into a per-session host dir
  (`CODE_SANDBOX_STAGING_DIR`, `data/sandbox-staging/<pid>-<id>`, not `/tmp`: the
  service runs with PrivateTmp) bind-mounted **read-only** at `/staging`; it runs
  `python /staging/code-<n>.py` in `/work`, and an exec as the sandbox user copies
  attachments into `/work/attachments`. Files come out through an exec that reads only
  a regular file directly in `/output` (no symlink, FIFO or device), up to
  `MAX_FILE_SIZE_BYTES`, under a 10 s `timeout`: the output list is parsed from stdout,
  which user code can forge (a `../dev/urandom` entry streamed into the app worker in
  review). Names with `/` or `..` are dropped before that.
- **The root kill is isolated**: the image's `HOME` and working dir are `/work`, so a
  root `python -c` would load a planted `/work/*.py` or user site-package; the kill runs
  `python -I -S` in `/` with `HOME=/root` (a live test plants both).
- **No host access**: Code cannot access files outside the container
- **Resource limits**: Configurable timeout (30s default), memory limit (512MB default)
- **Per-conversation sessions**: Containers are reused across `execute_code`
  calls within a conversation ([sandbox_sessions.py](../../src/agent/tools/sandbox_sessions.py):
  LRU pool, `CODE_SANDBOX_MAX_SESSIONS` per worker, idle TTL
  `CODE_SANDBOX_SESSION_TTL_SECONDS`). Files in `/work/` persist across calls;
  variables do NOT (each run is a fresh Python process); `/output/` is cleared
  at the start of every run. Without a conversation context the session is
  ephemeral (created and destroyed per call, the old behavior).
- **Orphan reaping**: Pooled containers are otherwise closed only by `atexit`,
  which a killed process (SIGTERM/SIGKILL of a test run, dev server or worker)
  skips. Every container is labelled `moneypenny.owner_pid`; when the pool
  starts it removes containers whose owner process is gone, and staging dirs whose
  `<pid>` prefix is dead. Tests close the
  pool after each test (`close_pooled_sandbox_sessions` in `tests/conftest.py`).

## Configuration

```bash
CODE_SANDBOX_ENABLED=true                    # Enable/disable (default: true)
CODE_SANDBOX_IMAGE=moneypenny-sandbox:local  # Custom Docker image (required)
CODE_SANDBOX_TIMEOUT_SECONDS=30                      # Execution timeout in seconds
CODE_SANDBOX_MEMORY_LIMIT=512m               # Container memory limit
CODE_SANDBOX_CPU_LIMIT=1.0                   # CPU limit (1.0 = 1 core)
CODE_SANDBOX_MAX_ATTACHMENTS=5               # Conversation files execute_code may copy into /work/attachments/ per call
CODE_SANDBOX_MAX_SESSIONS=2                  # Pooled sessions per worker
CODE_SANDBOX_SESSION_TTL_SECONDS=900         # Idle session lifetime
```

The sandbox container runs with **networking disabled** and the memory/CPU
limits above. Available Python libraries are baked into the Docker image
([docker/code-sandbox/Dockerfile](../../docker/code-sandbox/Dockerfile)) -
runtime installation is not possible without network. To add a library, add it
to the Dockerfile's `pip install` list **and** to the package list the model
sees - the "Pre-installed Libraries" section of the `execute_code` docstring,
the tool's only usage guide since Nov 14 2026 (the prompt's duplicate Code
Execution sections were removed) - then rebuild with `make sandbox-image`.
`TestSandboxLibraryListsMatchImage` in
[test_code_execution.py](../../tests/unit/test_code_execution.py) fails when
the list drifts from the Dockerfile (the model skips a library it was not
told about, or wastes a round on an import that fails).

## Stop

Pressing Stop while `execute_code` runs kills the user's program (SIGKILL to every process but PID 1 and the keep-alive `tail`, found by scanning `/proc` from Python as root - the slim image has no `pkill`) through a cancel callback registered around `session.run`; the run's own timeout (`CODE_SANDBOX_TIMEOUT_SECONDS`) uses the same kill. The session container and `/work` survive, so later calls in the conversation still see saved files. When no exec can start (a fork bomb holding every pid), the kill falls back to `docker kill` and the pool drops the session. See [Agent Graph - Stop Checkpoints](../architecture/agent-graph.md#stop-checkpoints).

## Office Files

The image ships python-docx, python-pptx and openpyxl (image label
`moneypenny.version=1.1`), so the agent can return real Word, PowerPoint and
Excel files rather than a PDF or markdown. The Code Execution prompt section
keeps only one-line pointers; the recipes live in the `office-documents` and
`pdf-documents` [skills](agent-tools.md#skills), loaded on demand. The
`office-documents` skill tells it to use the real format whenever the user
wants an editable document, with real structure (built-in heading/list styles,
real tables, slide layouts with title placeholders), Excel formatting (bold
header, frozen panes, column widths, number formats, formulas where values
should update), and a descriptive filename under `/output/`. Files come back
through the normal [file output pattern](#file-output-pattern-uses-_full_result-to-save-tokens).

## Conversation Files and PDFs (Nov 2026)

The user's uploads are not in the sandbox by default. `execute_code(code, files=[...])`
takes file ids from the history metadata (`message_id:file_index`), loads each through
`conversation_files.load_conversation_file` - the same checks as `retrieve_file`: the
user's own conversation, the message belongs to it, the index exists, within retention -
and copies it to `/work/attachments/<safe name>` before the code runs (directories and
leading dots stripped, a repeated name gets `-2`; the result's `attachments` lists the
paths). Files attached to the **current** message have no history line yet, so the save
path gives them their id (`annotate_history_file_ids`, transient like the Files API URIs) and
`build_message_content` lists them beside the attachments. All files are checked before anything is copied; at most
`CODE_SANDBOX_MAX_ATTACHMENTS` (5) per call, each within `MAX_FILE_SIZE_BYTES`.

The image reads PDFs with `pypdf` and `pdfplumber` (text, words with coordinates, drawn
lines/rects, tables, page renders via `page.to_image`). `from sandbox_helpers import
pdf_overview` (`docker/code-sandbox/sandbox_helpers.py`, on `PYTHONPATH`) is the first
look: per page size, text characters, words, lines/rects and tables, ending with the
pages that have **no text** (scanned or drawn as images) and how to render them - never
silence. Pages print as they are read, 20 per call (`first_page=` for the next), so a
line-dense plan set cannot run into the 30 s timeout with nothing shown. This closed the floor-plan failure (Oct 2026): a PDF uploaded earlier is only
listed in later turns, and the sandbox had neither the file nor a PDF library. Evals:
`sandbox_pdf_floor_plan` (a file on an earlier turn - the harness stores history files
like uploads) and `sandbox_pdf_current_turn` (attached to the asking message).

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

`make update` builds the sandbox image only when it is **missing** (a failed
build warns and the deploy goes on). It does not rebuild an existing one: after
a Dockerfile change (e.g. the 1.1 office libraries), run `make sandbox-image` on
the production host as well, or the running image keeps the old library set
while the prompt already advertises the new one.

**Never `docker image prune -a` on the production host.** The sandbox image has
no container between runs, so an `-a` prune deletes it as unused. In Nov 2026
a disk cleanup did exactly that, and code execution was off for three days.
Use a plain `docker image prune` (dangling images only).

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
- PDF document generation (reportlab, fpdf2)
- Word, PowerPoint and Excel files (python-docx, python-pptx, openpyxl)
- JSON/CSV data transformation

## Graceful Degradation

- If Docker is not available, the tool returns a non-retriable error naming
  the cause: a missing sandbox image ("run `make sandbox-image`") or Docker
  itself. The journal has the same split ("Custom sandbox image not found" vs
  "Docker command failed"/"Docker not available ..."): check it before
  suspecting Docker.
- A passing probe is cached for the worker's life; a failed one is retried
  after `_RECHECK_UNAVAILABLE_SECONDS` (60 s), so rebuilding the image or
  starting Docker takes effect without a restart
- The tool is only added to the available tools list if `CODE_SANDBOX_ENABLED=true` (`is_code_sandbox_available()` additionally checks Docker)

## Key Files

- [code_execution.py](../../src/agent/tools/code_execution.py) - `execute_code()` tool, `is_code_sandbox_available()`, `_check_docker_available()`
- [code_execution_output.py](../../src/agent/tools/code_execution_output.py) - the wrapper/output protocol: `wrap_user_code()`, the `/output` file marker, the response with `_full_result`
- [docker_sandbox.py](../../src/agent/tools/docker_sandbox.py) - `DockerSandbox` (container, staging, run, files in/out, kill) and `sandbox_container_config()` (every constraint)
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
from src.agent.tools.sandbox_sessions import make_sandbox_session
s = make_sandbox_session(); s.open()
try:
    print(s.run('import os; print(os.getuid(), 1+1)', timeout_s=30).stdout)
finally:
    s.close()
"
```

## Testing

- Unit: [test_sandbox_sessions.py](../../tests/unit/test_sandbox_sessions.py), `execute_code` cases in [test_code_execution.py](../../tests/unit/test_code_execution.py)
- Unit: `TestSandboxLibraryListsMatchImage` in [test_code_execution.py](../../tests/unit/test_code_execution.py) keeps the prompt and docstring package lists equal to the Dockerfile
- Integration: [test_sandbox_docker.py](../../tests/integration/test_sandbox_docker.py) (non-root, read-only root, ENOSPC, fork bomb, long scripts, files in/out, Stop, cleanup), [test_code_sandbox_isolation.py](../../tests/integration/test_code_sandbox_isolation.py) (needs Docker), [test_code_sandbox_office_files.py](../../tests/integration/test_code_sandbox_office_files.py) (writes real `.docx`/`.pptx`/`.xlsx` in the sandbox; skips without Docker or the image)

## See Also

- [Setup](../setup.md) - installing Docker and building the sandbox image
- [Agent Graph](../architecture/agent-graph.md#tool-node) - the `_full_result` capture/strip step
- [Image Generation](image-generation.md) - the other tool that returns files
