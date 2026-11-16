# Agent safety hardening - design

Nov 16 2026. Approved as proposed ("build the agent safety as proposed"), sandbox
disk option A (memory-backed, hard cap). From the Nov 15 2026 audit (TODO "Agent safety").

## Why

Moneypenny reads text other people wrote (web pages, a stranger's calendar
invite, a shared Todoist project, uploaded files) and runs scheduled agents
nobody watches. Three gaps let that text or code do more than it should:

1. **Store namespaces** - `kv_store` refuses only the app's reserved
   namespaces. An instruction planted in a page can make a run or a chat write
   or delete `sports`, `places` or another agent's `agent:<id>` data.
2. **Untrusted framing** - only web results are framed as data
   (`wrap_untrusted_content`); calendar, Todoist, file and past-chat text
   reach the model as if the tool itself said it.
3. **Sandbox** - `execute_code` runs as root, with no process limit, all
   default capabilities, and an unbounded disk: one run can fill the
   production host's disk (ext4: Docker cannot quota a container).

Non-goals: Gemini safety settings and an output cap (separate TODO item);
a permission model per namespace; framing the user's own chat messages.
Anti-goals: breaking the Daily Briefing (reads `sports` and `places`), the
sports and language coaches (write their own namespace), Stop killing a
running program, or files moving in and out of `/work`.

## Production facts (Nov 16 2026)

- Every scheduled agent writes only its own `agent:<id>`; the briefing
  reads `sports` and `places`; places are written by `save_place`, not
  `kv_store`. Standing chats write their own namespace (`sports`,
  `language`, `agent:<id>`).
- Docker on the production host: overlayfs (containerd snapshotter) on ext4.

## Design

### 1. Namespaces: write your own, read any

`kv_store` `set`, `merge` and `delete` succeed only on the turn's own
namespace (the run's `agent:<job id>`, or the standing chat's namespace);
any other namespace is a non-retriable error naming the own one. `get` and
`list` stay open on every non-reserved namespace. Applies to runs and to
standing chats alike (an injected page in a watched chat writes silently
too). The tool description says so. A "kv write refused" log line
(`user_id`, `namespace`, `own`).

### 2. Untrusted framing in the tool node

One wrapper applied in the tool node to the results of a set of tools
whose text other people can write: `google_calendar`, `todoist`,
`retrieve_file` / file reads, `search_conversations`, `read_conversation`
(past chats can hold pasted outside text). Generalise
`wrap_untrusted_content(text, source)` with a `kind` ("web content",
"calendar data", ...); results that are tool errors or already framed are
left alone. Structured (JSON) results are framed as a whole. Cost ~40 tokens
per framed result. Evals: 2-3 cases with an injected instruction in a
calendar event / Todoist task / past chat (fake integrations), graded by
`forbidden_tools` (e.g. `manage_memory`, `kv_store`, `todoist` writes).

### 3. Sandbox

- **User**: the image gets a `sandbox` user (uid 10001); code runs as it.
- **Limits**: `pids_limit` 128; `cap_drop` ALL with `cap_add` KILL only
  (the Stop kill runs as root and must signal uid 10001);
  `security_opt` `no-new-privileges`.
- **Disk (option A)**: `read_only` root filesystem; `tmpfs` for `/work`
  (256 MB), `/output` (64 MB) and `/tmp` (64 MB), owned by uid 10001. tmpfs pages count against the container's 512 MB
  memory limit, so a full disk becomes a failed write inside the sandbox,
  never the host's.
- **Spike (Nov 16 2026, local Docker, throwaway)** confirmed: uid 10001 runs code; the
  read-only root refuses writes; a 300 MB write to the 256 MB `/work` stops at 256 MiB
  and the container lives; a fork bomb stops at 124 processes (`pids_limit` 128); a root
  exec with only KILL kills a uid 10001 program. It also showed: Docker's copy neither
  sees tmpfs (`get_archive` 404) nor writes a read-only root (`put_archive` 400), so
  llm-sandbox's `run` (code file copied into `/sandbox`) cannot work; and during a fork
  bomb a new exec can fail to start (`Resource temporarily unavailable`), while
  `docker kill` stops the container in 0.04 s.
- **Our own session over docker-py (replaces llm-sandbox)**: llm-sandbox is used for
  open/close, `run`, two copies and `container.exec_run` only. A `DockerSandbox` class
  creates the container with the settings above plus a per-session host staging
  directory bind-mounted **read-only** at `/staging` (uid 10001 cannot write it - verified).
  - Code: the app writes `code-<n>.py` into the host staging dir; exec
    `python /staging/code-<n>.py` as uid 10001 in `/work`, demuxed stdout/stderr, under
    `CODE_SANDBOX_TIMEOUT_SECONDS` (the exec runs on a thread; on timeout the root kill
    runs, and if that exec cannot start, `docker kill` and the session is dropped -
    `/work` is lost only then).
  - Files in: the app writes the file into staging; an exec as uid 10001 copies it into
    `/work/attachments`. Files out: exec `cat /output/<f>` (binary-safe, verified 5 MB).
  - Close: remove the container and the staging dir. The orphan reaper also removes
    staging dirs whose container is gone.
  - The image gets the `sandbox` user (uid 10001: not a likely host uid) and the requirement
    `llm-sandbox[docker]` becomes `docker`.
- **Instrument**: the "Code execution" log line gains `work_bytes` (du of
  `/work` after the run); a write failing with ENOSPC is reported to the
  model as "the sandbox disk is full (256 MB)".

## Approaches considered

- Sandbox disk: (A) memory-backed folders with a hard cap - chosen; (B) a
  size check after each run - simple, but one 30 s run can write gigabytes
  first; (C) a loop-mounted image per session - real disk quota, but root
  on the host and slow setup.
- Namespaces: own-namespace writes everywhere (chosen) vs runs only (the
  audit's wording) - an interactive turn reading a page is as exposed as a
  run.
- Framing: one wrapper in the tool node (chosen) vs each tool framing its
  own result (more places to forget).

## Left to the builder

Exact tmpfs sizes within the memory limit; the frame wording per kind; which
`retrieve_file` actions count as file reads; eval fixtures.

## Verification

Unit tests per piece (namespace writes and reads, framing per tool and not
for errors, sandbox runtime config), an integration test against Docker
(skipped without it): non-root, pids, ENOSPC, attachments in, outputs out,
Stop kills. `make sandbox-image` locally and on the production host before
the deploy (the image is built there). Evals: the injection cases plus the
code-execution cases before/after; cost reported. Re-measure ~Nov 30: "kv
write refused" lines (a legitimate agent refused = a bug), `work_bytes`,
code-execution failures against the two weeks before.
