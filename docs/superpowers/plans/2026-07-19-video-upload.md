# Video Upload & Consultation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Users upload short videos (<1 min, ≤100MB) from iPhone/Android and consult the AI about their content; follow-ups re-access the video on demand; media is auto-cleaned (videos 7 days, images 30 days).

**Architecture:** Videos ride the existing base64-in-JSON chat request and blob storage. Server bridges to the Gemini Files API (inline Gemini requests cap at ~20MB) and caches the 48h `file_uri` in `kv_store`. The video is sent to the model only on its upload turn; later turns use the `retrieve_file` tool. A daily sweep deletes expired media; expiry is derived from message age so history labels and `retrieve_file` errors stay truthful even before the sweep runs.

**Tech Stack:** Flask + APIFlask, `google-genai` (Files API), `langchain-google-genai` (media blocks), SQLite blob store, Vite/TypeScript frontend, pytest + vitest + Playwright.

**Spec:** `docs/superpowers/specs/2026-07-19-video-upload-design.md`

## Global Constraints

- Video MIME types: exactly `video/mp4`, `video/quicktime`, `video/webm`.
- Video size cap: 100MB (`MAX_VIDEO_FILE_SIZE`); other types keep 20MB `MAX_FILE_SIZE`.
- Retention: videos 7 days (`VIDEO_RETENTION_DAYS`), images 30 days (`IMAGE_RETENTION_DAYS`); PDFs/text unaffected; thumbnails are never deleted.
- Gemini file URI cache: kv_store user_id `"_system"`, namespace `"gemini_files"`, key `"{message_id}:{file_index}"`, TTL 47 hours.
- LangChain media block shape: `{"type": "media", "file_uri": <uri>, "mime_type": <mime>}`.
- Message timestamps are **naive local** datetimes — compare with `datetime.now()` (same convention as `src/api/routes/files.py` stale-thumbnail check). kv_store timestamps use `utcnow_naive()`.
- JWT is sent via `Authorization` header only — media playback must blob-fetch through the API client, never bare `<video src>`.
- A PostToolUse hook auto-formats after every edit; still run `make lint` before each commit.
- Conventional Commits: `type(scope): description`.
- New env vars go into `src/config.py` with defaults AND `.env.example`.

---

### Task 1: Backend video MIME types + per-type size validation

**Files:**
- Modify: `src/config.py:208-216` (file upload settings), `src/config.py:~607` (validation)
- Modify: `src/utils/files.py:16` (`MIME_TYPE_ALIASES`), `src/utils/files.py:~175` (size check in `validate_files`)
- Modify: `.env.example`
- Test: `tests/unit/test_files.py`

**Interfaces:**
- Produces: `Config.MAX_VIDEO_FILE_SIZE: int`, `Config.VIDEO_RETENTION_DAYS: int`, `Config.IMAGE_RETENTION_DAYS: int`, `max_size_for_mime(mime_type: str) -> int` in `src/utils/files.py`. Videos accepted by `validate_files`.

- [ ] **Step 1: Write failing tests**

Add to `tests/unit/test_files.py` (follow the file's existing fixture style — it already tests `validate_files` / `verify_file_type_by_magic`):

```python
# Minimal valid container headers — enough for libmagic detection
MP4_HEADER = b"\x00\x00\x00\x20ftypisom\x00\x00\x02\x00isomiso2avc1mp41" + b"\x00" * 64
MOV_HEADER = b"\x00\x00\x00\x14ftypqt  \x00\x00\x00\x00qt  " + b"\x00" * 64


class TestVideoValidation:
    def test_mp4_video_is_allowed(self):
        files = [{"name": "clip.mp4", "type": "video/mp4",
                  "data": base64.b64encode(MP4_HEADER).decode()}]
        is_valid, error = validate_files(files)
        assert is_valid, error

    def test_quicktime_video_is_allowed(self):
        files = [{"name": "clip.mov", "type": "video/quicktime",
                  "data": base64.b64encode(MOV_HEADER).decode()}]
        is_valid, error = validate_files(files)
        assert is_valid, error

    def test_video_uses_video_size_limit(self, monkeypatch):
        monkeypatch.setattr(Config, "MAX_VIDEO_FILE_SIZE", 100)
        big = MP4_HEADER + b"\x00" * 200
        files = [{"name": "clip.mp4", "type": "video/mp4",
                  "data": base64.b64encode(big).decode()}]
        is_valid, error = validate_files(files)
        assert not is_valid
        assert "clip.mp4" in error

    def test_image_still_uses_default_limit(self, monkeypatch):
        # A video-sized image must NOT get the video allowance
        monkeypatch.setattr(Config, "MAX_FILE_SIZE", 100)
        monkeypatch.setattr(Config, "MAX_VIDEO_FILE_SIZE", 10_000)
        png = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"\x00" * 200).decode()
        files = [{"name": "big.png", "type": "image/png", "data": png}]
        is_valid, error = validate_files(files)
        assert not is_valid

    def test_spoofed_video_rejected(self):
        # PNG bytes claiming to be a video
        png_bytes = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
        files = [{"name": "fake.mp4", "type": "video/mp4",
                  "data": base64.b64encode(png_bytes).decode()}]
        is_valid, error = validate_files(files)
        assert not is_valid
```

- [ ] **Step 2: Run tests, verify they fail**

Run: `.venv/bin/pytest tests/unit/test_files.py -k Video -v`
Expected: FAIL — `video/mp4` not in `ALLOWED_FILE_TYPES` ("File type 'video/mp4' is not allowed").

- [ ] **Step 3: Implement config changes**

In `src/config.py`, after `MAX_FILE_SIZE` (line ~208):

```python
    MAX_VIDEO_FILE_SIZE: int = int(
        os.getenv("MAX_VIDEO_FILE_SIZE", str(100 * BYTES_PER_MB))
    )  # 100 MB
    # Media retention: attachments are not permanent storage
    VIDEO_RETENTION_DAYS: int = int(os.getenv("VIDEO_RETENTION_DAYS", "7"))
    IMAGE_RETENTION_DAYS: int = int(os.getenv("IMAGE_RETENTION_DAYS", "30"))
```

Extend the `ALLOWED_FILE_TYPES` default string with `,video/mp4,video/quicktime,video/webm`.

In the config validation section (~line 607), next to the `MAX_FILE_SIZE` check:

```python
        if cls.MAX_VIDEO_FILE_SIZE < 1:
            errors.append(
                f"MAX_VIDEO_FILE_SIZE must be positive, got {cls.MAX_VIDEO_FILE_SIZE}"
            )
```

- [ ] **Step 4: Implement validation changes**

In `src/utils/files.py`, add video entries to `MIME_TYPE_ALIASES`:

```python
    # Videos - libmagic detects container formats; .mov sometimes reads as mp4 family
    "video/mp4": {"video/mp4", "video/x-m4v"},
    "video/quicktime": {"video/quicktime", "video/mp4"},
    "video/webm": {"video/webm", "video/x-matroska"},
```

Add a helper above `validate_files` and use it in the size check (replacing the direct `Config.MAX_FILE_SIZE` comparison):

```python
def max_size_for_mime(mime_type: str) -> int:
    """Per-type upload size limit (videos get a larger allowance)."""
    if mime_type.startswith("video/"):
        return Config.MAX_VIDEO_FILE_SIZE
    return Config.MAX_FILE_SIZE
```

```python
            max_size = max_size_for_mime(file_type)
            if len(decoded_data) > max_size:
                max_mb = max_size / (1024 * 1024)
                ...
                return False, f"File '{file_name}' exceeds {max_mb:.0f}MB limit"
```

(Keep the existing `logger.warning` block, just switch it to `max_size`.)

- [ ] **Step 5: Update `.env.example`** — add `MAX_VIDEO_FILE_SIZE`, `VIDEO_RETENTION_DAYS`, `IMAGE_RETENTION_DAYS` with comments, and the new default `ALLOWED_FILE_TYPES` string if it's listed there.

- [ ] **Step 6: Run tests, verify they pass**

Run: `.venv/bin/pytest tests/unit/test_files.py tests/unit/test_config.py -v`
Expected: PASS (all, including pre-existing).

- [ ] **Step 7: Commit**

```bash
git add src/config.py src/utils/files.py .env.example tests/unit/test_files.py
git commit -m "feat(files): accept video uploads with per-type size limits"
```

---

### Task 2: Upload config surface → frontend acceptance

**Files:**
- Modify: `src/api/schemas.py:591-596` (`UploadConfigResponse`)
- Modify: `src/api/routes/system.py:55-66` (`get_upload_config`)
- Modify: `web/src/types/api.ts:125` (`UploadConfig`)
- Modify: `web/src/state/store.ts:296-310` (`DEFAULT_UPLOAD_CONFIG`)
- Modify: `web/src/config.ts:315` (`UPLOAD_ALLOWED_TYPES`)
- Modify: `web/src/components/FileUpload.ts` (size check + exported helper)
- Modify: `web/src/core/init.ts:143` (file input `accept`)
- Test: `tests/integration/test_routes_kv_memory_system.py:168` (existing `/api/config/upload` test), new `web/tests/unit/file-upload.test.ts`

**Interfaces:**
- Consumes: `Config.MAX_VIDEO_FILE_SIZE` (Task 1).
- Produces: `UploadConfig.maxVideoFileSize: number` (frontend type + API response field `maxVideoFileSize`), exported `maxSizeForType(config: UploadConfig, mimeType: string): number` in `FileUpload.ts`.

- [ ] **Step 1: Write failing backend test** — in the existing `/api/config/upload` test (`tests/integration/test_routes_kv_memory_system.py:168`), assert:

```python
        assert data["maxVideoFileSize"] == 100 * 1024 * 1024
        assert "video/mp4" in data["allowedFileTypes"]
```

Run: `.venv/bin/pytest tests/integration/test_routes_kv_memory_system.py -k upload -v` — expect FAIL (KeyError).

- [ ] **Step 2: Implement backend** — `src/api/schemas.py`:

```python
    maxVideoFileSize: int = Field(..., description="Maximum video file size in bytes")
```

`src/api/routes/system.py` `get_upload_config` return dict:

```python
        "maxVideoFileSize": Config.MAX_VIDEO_FILE_SIZE,
```

Run the test again — expect PASS.

- [ ] **Step 3: Regenerate TS types**

Run: `make types`
Expected: `web/src/types/generated-api.ts` updated with `maxVideoFileSize`.

- [ ] **Step 4: Write failing frontend test** — create `web/tests/unit/file-upload.test.ts`:

```typescript
import { describe, it, expect } from 'vitest';
import { maxSizeForType } from '../../src/components/FileUpload';
import type { UploadConfig } from '../../src/types/api';

const config: UploadConfig = {
  maxFileSize: 20 * 1024 * 1024,
  maxVideoFileSize: 100 * 1024 * 1024,
  maxFilesPerMessage: 10,
  allowedFileTypes: ['image/png', 'video/mp4'],
};

describe('maxSizeForType', () => {
  it('returns video limit for video MIME types', () => {
    expect(maxSizeForType(config, 'video/mp4')).toBe(100 * 1024 * 1024);
    expect(maxSizeForType(config, 'video/quicktime')).toBe(100 * 1024 * 1024);
  });

  it('returns default limit for non-video types', () => {
    expect(maxSizeForType(config, 'image/png')).toBe(20 * 1024 * 1024);
    expect(maxSizeForType(config, 'application/pdf')).toBe(20 * 1024 * 1024);
  });
});
```

Run: `cd web && npx vitest run tests/unit/file-upload.test.ts` — expect FAIL (no export).

- [ ] **Step 5: Implement frontend**

`web/src/types/api.ts` — add `maxVideoFileSize: number;` to `UploadConfig`.

`web/src/state/store.ts` `DEFAULT_UPLOAD_CONFIG` — add `maxVideoFileSize: 100 * 1024 * 1024,` and append `'video/mp4', 'video/quicktime', 'video/webm'` to `allowedFileTypes`.

`web/src/config.ts` `UPLOAD_ALLOWED_TYPES` — append the same three video types.

`web/src/components/FileUpload.ts` — export the helper and use it in `addFilesToPending`; also give videos a local preview URL (video elements accept blob URLs):

```typescript
/** Per-type upload size limit (videos get a larger allowance) */
export function maxSizeForType(config: UploadConfig, mimeType: string): number {
  return mimeType.startsWith('video/') ? config.maxVideoFileSize : config.maxFileSize;
}
```

In the size check:

```typescript
    const maxSize = maxSizeForType(uploadConfig, file.type);
    if (file.size > maxSize) {
      const maxMB = maxSize / (1024 * 1024);
      toast.warning(`File '${file.name}' exceeds ${maxMB}MB limit`);
      continue;
    }
```

In the `FileUpload` construction, extend `previewUrl`:

```typescript
        previewUrl:
          file.type.startsWith('image/') || file.type.startsWith('video/')
            ? URL.createObjectURL(file)
            : undefined,
```

(Import `UploadConfig` type in FileUpload.ts.)

`web/src/core/init.ts:143` — add an `accept` attribute so mobile browsers offer camera/library:

```html
<input type="file" id="file-input" multiple accept="image/*,video/mp4,video/quicktime,video/webm,application/pdf,text/plain,text/markdown,text/csv,application/json">
```

- [ ] **Step 6: Run tests**

Run: `cd web && npx vitest run` — expect PASS (including existing message-input tests; if `renderFilePreview` shows videos oddly, that's Task 10's scope — only fix type errors here).

- [ ] **Step 7: Commit**

```bash
git add src/api/schemas.py src/api/routes/system.py web/src/types/ web/src/state/store.ts web/src/config.ts web/src/components/FileUpload.ts web/src/core/init.ts web/tests/unit/file-upload.test.ts tests/integration/test_routes_kv_memory_system.py
git commit -m "feat(upload): surface video limits to frontend and accept video files"
```

---

### Task 3: Media retention helpers

**Files:**
- Create: `src/utils/media_retention.py`
- Test: `tests/unit/test_media_retention.py`

**Interfaces:**
- Consumes: `Config.VIDEO_RETENTION_DAYS`, `Config.IMAGE_RETENTION_DAYS` (Task 1).
- Produces: `retention_days_for_mime(mime_type: str) -> int | None`, `is_media_expired(mime_type: str, created_at: datetime, now: datetime | None = None) -> bool`, `retention_note(mime_type: str) -> str`.

- [ ] **Step 1: Write failing tests** — `tests/unit/test_media_retention.py`:

```python
"""Tests for media retention helpers."""

from datetime import datetime, timedelta

from src.utils.media_retention import (
    is_media_expired,
    retention_days_for_mime,
    retention_note,
)


class TestRetentionDays:
    def test_video_retention(self):
        assert retention_days_for_mime("video/mp4") == 7
        assert retention_days_for_mime("video/quicktime") == 7

    def test_image_retention(self):
        assert retention_days_for_mime("image/png") == 30

    def test_non_media_has_no_retention(self):
        assert retention_days_for_mime("application/pdf") is None
        assert retention_days_for_mime("text/plain") is None


class TestIsMediaExpired:
    def test_fresh_video_not_expired(self):
        now = datetime(2026, 7, 19, 12, 0)
        created = now - timedelta(days=6)
        assert not is_media_expired("video/mp4", created, now=now)

    def test_old_video_expired(self):
        now = datetime(2026, 7, 19, 12, 0)
        created = now - timedelta(days=8)
        assert is_media_expired("video/mp4", created, now=now)

    def test_image_expires_after_30_days(self):
        now = datetime(2026, 7, 19, 12, 0)
        assert not is_media_expired("image/png", now - timedelta(days=29), now=now)
        assert is_media_expired("image/png", now - timedelta(days=31), now=now)

    def test_pdf_never_expires(self):
        now = datetime(2026, 7, 19, 12, 0)
        assert not is_media_expired("application/pdf", now - timedelta(days=999), now=now)


class TestRetentionNote:
    def test_notes(self):
        assert "7 days" in retention_note("video/mp4")
        assert "30 days" in retention_note("image/png")
```

Run: `.venv/bin/pytest tests/unit/test_media_retention.py -v` — expect FAIL (module missing).

- [ ] **Step 2: Implement** — `src/utils/media_retention.py`:

```python
"""Media retention policy helpers.

Media attachments are not permanent storage: videos are retained for
VIDEO_RETENTION_DAYS, images for IMAGE_RETENTION_DAYS. Expiry is derived
from message age, so callers (history labeling, retrieve_file, file routes)
stay truthful even before the physical sweep has run.

Message timestamps are naive local datetimes; compare with datetime.now().
"""

from datetime import datetime, timedelta

from src.config import Config


def retention_days_for_mime(mime_type: str) -> int | None:
    """Retention window in days for a MIME type, or None if never expires."""
    if mime_type.startswith("video/"):
        return Config.VIDEO_RETENTION_DAYS
    if mime_type.startswith("image/"):
        return Config.IMAGE_RETENTION_DAYS
    return None


def is_media_expired(
    mime_type: str, created_at: datetime, now: datetime | None = None
) -> bool:
    """Whether a media file has passed its retention window."""
    days = retention_days_for_mime(mime_type)
    if days is None:
        return False
    now = now or datetime.now()
    return created_at < now - timedelta(days=days)


def retention_note(mime_type: str) -> str:
    """Human/LLM-readable description of the retention policy for a type."""
    days = retention_days_for_mime(mime_type)
    if days is None:
        return "This file type is not subject to retention cleanup"
    kind = "Videos" if mime_type.startswith("video/") else "Images"
    return f"{kind} are retained for {days} days"
```

- [ ] **Step 3: Run tests** — `.venv/bin/pytest tests/unit/test_media_retention.py -v` — expect PASS.

- [ ] **Step 4: Commit**

```bash
git add src/utils/media_retention.py tests/unit/test_media_retention.py
git commit -m "feat(retention): add media retention policy helpers"
```

---

### Task 4: Gemini Files API bridge

**Files:**
- Create: `src/agent/gemini_files.py`
- Test: `tests/unit/test_gemini_files.py`

**Interfaces:**
- Consumes: `Config.GEMINI_API_KEY`, `db.kv_get/kv_set/kv_delete` (`src/db/models/kv_store.py:35-96`), `utcnow_naive` (`src/utils/datetime_utils.py` — verify exact import; kv_store.py already imports it).
- Produces:
  - `class GeminiFileError(Exception)`
  - `ensure_gemini_file_uri(message_id: str, file_index: int, data: bytes, mime_type: str) -> str`
  - `attach_gemini_file_uris(message_id: str, files: list[dict[str, Any]]) -> None` (mutates: adds `gemini_file_uri` or `gemini_upload_error` to video file dicts)
  - `delete_cached_file_uri(message_id: str, file_index: int) -> None`
  - Constants: `GEMINI_FILES_NAMESPACE = "gemini_files"`, `SYSTEM_KV_USER_ID = "_system"`

- [ ] **Step 1: Write failing tests** — `tests/unit/test_gemini_files.py`. Mock the genai client; use the existing test DB fixture from `tests/conftest.py` for kv_store (look at how other unit tests get a `db`; follow that pattern):

```python
"""Tests for the Gemini Files API bridge."""

import base64
import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from src.agent.gemini_files import (
    GEMINI_FILES_NAMESPACE,
    SYSTEM_KV_USER_ID,
    GeminiFileError,
    attach_gemini_file_uris,
    ensure_gemini_file_uri,
)
from src.db.models import db


def _mock_client(state_sequence=("ACTIVE",), uri="https://files.example/f1"):
    """Build a genai client mock whose files.get walks state_sequence."""
    client = MagicMock()
    uploaded = SimpleNamespace(
        name="files/f1", uri=uri, state=SimpleNamespace(name=state_sequence[0])
    )
    client.files.upload.return_value = uploaded
    states = [
        SimpleNamespace(name="files/f1", uri=uri, state=SimpleNamespace(name=s))
        for s in state_sequence[1:]
    ]
    client.files.get.side_effect = states
    return client


class TestEnsureGeminiFileUri:
    def test_uploads_and_caches(self):
        client = _mock_client(("ACTIVE",))
        with patch("src.agent.gemini_files._get_client", return_value=client):
            uri = ensure_gemini_file_uri("msg-1", 0, b"vid", "video/mp4")
        assert uri == "https://files.example/f1"
        cached = db.kv_get(SYSTEM_KV_USER_ID, GEMINI_FILES_NAMESPACE, "msg-1:0")
        assert cached is not None
        assert json.loads(cached)["uri"] == uri

    def test_cache_hit_skips_upload(self):
        client = _mock_client(("ACTIVE",))
        with patch("src.agent.gemini_files._get_client", return_value=client):
            ensure_gemini_file_uri("msg-2", 0, b"vid", "video/mp4")
            ensure_gemini_file_uri("msg-2", 0, b"vid", "video/mp4")
        assert client.files.upload.call_count == 1

    def test_polls_until_active(self):
        client = _mock_client(("PROCESSING", "ACTIVE"))
        with (
            patch("src.agent.gemini_files._get_client", return_value=client),
            patch("src.agent.gemini_files.time.sleep"),
        ):
            uri = ensure_gemini_file_uri("msg-3", 0, b"vid", "video/mp4")
        assert uri == "https://files.example/f1"

    def test_failed_processing_raises(self):
        client = _mock_client(("PROCESSING", "FAILED"))
        with (
            patch("src.agent.gemini_files._get_client", return_value=client),
            patch("src.agent.gemini_files.time.sleep"),
            pytest.raises(GeminiFileError),
        ):
            ensure_gemini_file_uri("msg-4", 0, b"vid", "video/mp4")


class TestAttachGeminiFileUris:
    def test_attaches_uri_to_videos_only(self):
        client = _mock_client(("ACTIVE",))
        files = [
            {"name": "a.png", "type": "image/png", "data": base64.b64encode(b"x").decode()},
            {"name": "b.mp4", "type": "video/mp4", "data": base64.b64encode(b"v").decode()},
        ]
        with patch("src.agent.gemini_files._get_client", return_value=client):
            attach_gemini_file_uris("msg-5", files)
        assert "gemini_file_uri" not in files[0]
        assert files[1]["gemini_file_uri"] == "https://files.example/f1"

    def test_upload_failure_sets_error_not_exception(self):
        client = _mock_client(("PROCESSING", "FAILED"))
        files = [{"name": "b.mp4", "type": "video/mp4",
                  "data": base64.b64encode(b"v").decode()}]
        with (
            patch("src.agent.gemini_files._get_client", return_value=client),
            patch("src.agent.gemini_files.time.sleep"),
        ):
            attach_gemini_file_uris("msg-6", files)
        assert "gemini_file_uri" not in files[0]
        assert "gemini_upload_error" in files[0]
```

Run: `.venv/bin/pytest tests/unit/test_gemini_files.py -v` — expect FAIL (module missing).

- [ ] **Step 2: Implement** — `src/agent/gemini_files.py`:

```python
"""Bridge to the Gemini Files API for large media (videos).

Gemini's inline generateContent limit is ~20MB, so videos are uploaded to
the Files API and referenced by file_uri. Uploaded files live 48h on
Google's side; we cache the URI in kv_store for 47h and re-upload on demand.
"""

import base64
import binascii
import io
import json
import time
from datetime import timedelta
from typing import Any

from google import genai
from google.genai import types as genai_types

from src.config import Config
from src.db.models import db
from src.utils.datetime_utils import utcnow_naive
from src.utils.logging import get_logger

logger = get_logger(__name__)

GEMINI_FILES_NAMESPACE = "gemini_files"
SYSTEM_KV_USER_ID = "_system"
CACHE_TTL_HOURS = 47  # Gemini keeps files 48h; refresh one hour early
POLL_INTERVAL_SECONDS = 2
PROCESSING_TIMEOUT_SECONDS = 120


class GeminiFileError(Exception):
    """Raised when uploading or processing a file via the Files API fails."""


def _get_client() -> genai.Client:
    return genai.Client(api_key=Config.GEMINI_API_KEY)


def _cache_key(message_id: str, file_index: int) -> str:
    return f"{message_id}:{file_index}"


def _get_cached_uri(message_id: str, file_index: int) -> str | None:
    raw = db.kv_get(SYSTEM_KV_USER_ID, GEMINI_FILES_NAMESPACE, _cache_key(message_id, file_index))
    if not raw:
        return None
    try:
        entry = json.loads(raw)
        if utcnow_naive().isoformat() < entry["expires_at"]:
            return str(entry["uri"])
    except (json.JSONDecodeError, KeyError, TypeError):
        pass
    return None


def ensure_gemini_file_uri(
    message_id: str, file_index: int, data: bytes, mime_type: str
) -> str:
    """Return an ACTIVE Gemini Files API URI for this file, uploading if needed.

    Raises:
        GeminiFileError: if upload or server-side processing fails.
    """
    cached = _get_cached_uri(message_id, file_index)
    if cached:
        logger.debug(
            "Gemini file URI cache hit",
            extra={"message_id": message_id, "file_index": file_index},
        )
        return cached

    client = _get_client()
    logger.info(
        "Uploading file to Gemini Files API",
        extra={"message_id": message_id, "file_index": file_index,
               "mime_type": mime_type, "size": len(data)},
    )
    try:
        gfile = client.files.upload(
            file=io.BytesIO(data),
            config=genai_types.UploadFileConfig(mime_type=mime_type),
        )
        deadline = time.monotonic() + PROCESSING_TIMEOUT_SECONDS
        while gfile.state.name == "PROCESSING":
            if time.monotonic() > deadline:
                raise GeminiFileError("Timed out waiting for Gemini to process the file")
            time.sleep(POLL_INTERVAL_SECONDS)
            gfile = client.files.get(name=gfile.name)
    except GeminiFileError:
        raise
    except Exception as e:
        raise GeminiFileError(f"Gemini Files API upload failed: {e}") from e

    if gfile.state.name != "ACTIVE":
        raise GeminiFileError(f"Gemini file processing failed (state: {gfile.state.name})")

    expires_at = (utcnow_naive() + timedelta(hours=CACHE_TTL_HOURS)).isoformat()
    db.kv_set(
        SYSTEM_KV_USER_ID,
        GEMINI_FILES_NAMESPACE,
        _cache_key(message_id, file_index),
        json.dumps({"uri": gfile.uri, "name": gfile.name, "expires_at": expires_at}),
    )
    return str(gfile.uri)


def attach_gemini_file_uris(message_id: str, files: list[dict[str, Any]]) -> None:
    """Upload video attachments to the Files API, annotating file dicts in place.

    Adds "gemini_file_uri" on success or "gemini_upload_error" on failure.
    Never raises — a failed video upload must not fail the whole chat request.
    """
    for idx, file in enumerate(files):
        mime_type = file.get("type", "")
        if not mime_type.startswith("video/"):
            continue
        try:
            data = base64.b64decode(file.get("data", ""))
            file["gemini_file_uri"] = ensure_gemini_file_uri(message_id, idx, data, mime_type)
        except (GeminiFileError, binascii.Error) as e:
            logger.error(
                "Failed to prepare video for Gemini",
                extra={"message_id": message_id, "file_index": idx, "error": str(e)},
            )
            file["gemini_upload_error"] = str(e)


def delete_cached_file_uri(message_id: str, file_index: int) -> None:
    """Drop the cached Files API URI (used by the retention sweep)."""
    db.kv_delete(SYSTEM_KV_USER_ID, GEMINI_FILES_NAMESPACE, _cache_key(message_id, file_index))
```

Verify the `utcnow_naive` import path matches what `src/db/models/kv_store.py` uses; adjust if it lives elsewhere.

- [ ] **Step 3: Run tests** — `.venv/bin/pytest tests/unit/test_gemini_files.py -v` — expect PASS.

- [ ] **Step 4: Commit**

```bash
git add src/agent/gemini_files.py tests/unit/test_gemini_files.py
git commit -m "feat(agent): add Gemini Files API bridge with kv-cached URIs"
```

---

### Task 5: Send current-turn videos to the model

**Files:**
- Modify: `src/agent/agent.py:180-244` (`_build_message_content`)
- Modify: `src/api/routes/chat.py` (both batch and streaming request paths — grep `queue_pending_thumbnails(` to find each; add the attach call right after, before the agent is invoked)
- Test: `tests/unit/test_chat_agent_helpers.py` (if `_build_message_content` isn't covered there, add a new class in that file), `tests/integration/test_routes_chat.py`

**Interfaces:**
- Consumes: `attach_gemini_file_uris` (Task 4).
- Produces: `_build_message_content` emits `{"type": "media", "file_uri", "mime_type"}` for video files that carry `gemini_file_uri`; degrades to a text notice otherwise.

- [ ] **Step 1: Write failing unit test** for the content builder (adapt to however the agent object is constructed in existing tests in `tests/unit/test_chat_agent_helpers.py`):

```python
class TestBuildMessageContentVideo:
    def test_video_with_uri_becomes_media_block(self, agent):
        files = [{"name": "clip.mp4", "type": "video/mp4", "data": "aaaa",
                  "gemini_file_uri": "https://files.example/f1"}]
        blocks = agent._build_message_content("what is this?", files)
        media = [b for b in blocks if isinstance(b, dict) and b.get("type") == "media"]
        assert media == [{
            "type": "media",
            "file_uri": "https://files.example/f1",
            "mime_type": "video/mp4",
        }]

    def test_video_without_uri_becomes_text_notice(self, agent):
        files = [{"name": "clip.mp4", "type": "video/mp4", "data": "aaaa",
                  "gemini_upload_error": "boom"}]
        blocks = agent._build_message_content("what is this?", files)
        texts = [b["text"] for b in blocks if isinstance(b, dict) and b.get("type") == "text"]
        assert any("could not be attached" in t for t in texts)
```

Run: `.venv/bin/pytest tests/unit/test_chat_agent_helpers.py -k Video -v` — expect FAIL (video falls into the text-file branch and gets skipped as non-UTF-8).

- [ ] **Step 2: Implement the content builder branch** — in `_build_message_content` (src/agent/agent.py:208), add between the image and PDF branches:

```python
            elif mime_type.startswith("video/"):
                # Videos go via the Gemini Files API (inline limit is ~20MB).
                # The URI is attached by attach_gemini_file_uris() before the
                # agent runs; absence means the upload failed.
                uri = file.get("gemini_file_uri")
                if uri:
                    blocks.append(
                        {"type": "media", "file_uri": uri, "mime_type": mime_type}
                    )
                else:
                    error = file.get("gemini_upload_error", "processing failed")
                    name = file.get("name", "video")
                    blocks.append(
                        {
                            "type": "text",
                            "text": f"[Video '{name}' could not be attached: {error}. "
                            "Tell the user the video could not be processed.]",
                        }
                    )
```

Run the unit tests — expect PASS.

- [ ] **Step 3: Wire the attach step into chat routes.** In `src/api/routes/chat.py`, immediately after each `queue_pending_thumbnails(user_msg.id, files)` call (there is one in the batch endpoint and one in the streaming endpoint — grep to confirm), add:

```python
    # Upload videos to the Gemini Files API and annotate files with URIs
    # (annotations are transient: the message was already saved without them)
    if files:
        attach_gemini_file_uris(user_msg.id, files)
```

Import `attach_gemini_file_uris` from `src.agent.gemini_files` at the top of the module. Keep the call after the DB save so the stored `files` JSON never contains the transient keys.

- [ ] **Step 4: Write integration test** — in `tests/integration/test_routes_chat.py`, following the file's existing chat-endpoint test pattern (mocked `chat_batch` returning the 4-tuple `(response, tool_results, usage_info, result_messages)`):

```python
def test_video_upload_triggers_gemini_files_attach(client, auth_headers, monkeypatch):
    attached = {}

    def fake_attach(message_id, files):
        attached["files"] = files

    monkeypatch.setattr("src.api.routes.chat.attach_gemini_file_uris", fake_attach)
    # ...existing chat_batch mock setup from neighboring tests...
    mp4 = base64.b64encode(
        b"\x00\x00\x00\x20ftypisom\x00\x00\x02\x00isomiso2avc1mp41" + b"\x00" * 64
    ).decode()
    response = client.post(
        "/api/chat",
        json={"message": "what is in this video?",
              "files": [{"name": "clip.mp4", "type": "video/mp4", "data": mp4}]},
        headers=auth_headers,
    )
    assert response.status_code == 200
    assert attached["files"][0]["name"] == "clip.mp4"
```

Adapt endpoint path/payload to match neighboring tests exactly. Run: `.venv/bin/pytest tests/integration/test_routes_chat.py -k video -v` — expect PASS.

- [ ] **Step 5: Real-API smoke test (manual, not committed).** Write `/private/tmp/.../scratchpad/verify_video_media_block.py` (scratchpad, NOT the repo):

```python
"""Spike: verify langchain-google-genai serializes media/file_uri blocks.

Run: .venv/bin/python verify_video_media_block.py /path/to/small.mp4
Requires GEMINI_API_KEY in env (source .env).
"""
import sys

from google import genai
from google.genai import types
from langchain_core.messages import HumanMessage
from langchain_google_genai import ChatGoogleGenerativeAI

from src.config import Config

client = genai.Client(api_key=Config.GEMINI_API_KEY)
f = client.files.upload(file=sys.argv[1],
                        config=types.UploadFileConfig(mime_type="video/mp4"))
import time
while f.state.name == "PROCESSING":
    time.sleep(2)
    f = client.files.get(name=f.name)
print("state:", f.state.name, "uri:", f.uri)

model = ChatGoogleGenerativeAI(model=Config.DEFAULT_MODEL, api_key=Config.GEMINI_API_KEY)
msg = HumanMessage(content=[
    {"type": "text", "text": "Describe this video in one sentence."},
    {"type": "media", "file_uri": f.uri, "mime_type": "video/mp4"},
])
print(model.invoke([msg]).content)
```

Record a 2-second video (or download any tiny mp4) and run it. **Expected: a one-sentence description.** If the media block is rejected, STOP and check the `langchain-google-genai` changelog for the current block shape (`{"type": "file", ...}` in newer versions); adjust the shape constant in `_build_message_content` and `retrieve_file` (Task 6), and update the Global Constraints line. This is the one externally-unverified assumption in the plan.

- [ ] **Step 6: Run full backend suite** — `.venv/bin/pytest tests/ -x -q` — expect PASS.

- [ ] **Step 7: Commit**

```bash
git add src/agent/agent.py src/api/routes/chat.py tests/unit/test_chat_agent_helpers.py tests/integration/test_routes_chat.py
git commit -m "feat(agent): send uploaded videos to Gemini via Files API media blocks"
```

---

### Task 6: `retrieve_file` video support + expiry-aware errors

**Files:**
- Modify: `src/agent/tools/file_retrieval.py` (docstring + retrieval logic)
- Test: existing test file covering `retrieve_file` (grep `retrieve_file` under `tests/unit/`; extend it, or create `tests/unit/test_file_retrieval.py` if none exists)

**Interfaces:**
- Consumes: `ensure_gemini_file_uri`, `GeminiFileError` (Task 4); `is_media_expired`, `retention_note` (Task 3).
- Produces: `retrieve_file` returns `[{"type": "text", ...}, {"type": "media", "file_uri", "mime_type"}]` for videos; JSON error with the retention note for expired media.

- [ ] **Step 1: Write failing tests** (adapt fixtures to the existing test file's style — it needs a message in the test DB and mocked conversation context):

```python
class TestRetrieveFileVideo:
    def test_video_returns_media_block(self, seeded_video_message, mock_context):
        with patch(
            "src.agent.gemini_files.ensure_gemini_file_uri",
            return_value="https://files.example/f1",
        ):
            result = retrieve_file.invoke(
                {"message_id": seeded_video_message.id, "file_index": 0}
            )
        assert isinstance(result, list)
        assert result[1] == {
            "type": "media",
            "file_uri": "https://files.example/f1",
            "mime_type": "video/mp4",
        }

    def test_expired_video_returns_cleanup_error(self, seeded_old_video_message, mock_context):
        result = retrieve_file.invoke(
            {"message_id": seeded_old_video_message.id, "file_index": 0}
        )
        data = json.loads(result)
        assert "cleaned up" in data["error"]
        assert "7 days" in data["error"]

    def test_expired_image_returns_cleanup_error(self, seeded_old_image_message, mock_context):
        result = retrieve_file.invoke(
            {"message_id": seeded_old_image_message.id, "file_index": 0}
        )
        data = json.loads(result)
        assert "cleaned up" in data["error"]
```

`seeded_old_video_message` = message inserted with `created_at` 8+ days in the past (insert directly via the model layer or SQL so the timestamp is controllable). Run — expect FAIL.

- [ ] **Step 2: Implement.** In `src/agent/tools/file_retrieval.py`:

(a) After `file_meta` / `mime_type` extraction (before the blob-store lookup), add the age-based expiry gate:

```python
    from src.utils.media_retention import is_media_expired, retention_note

    if is_media_expired(mime_type, message.created_at):
        return json.dumps(
            {
                "error": f"This file has been cleaned up and is no longer available. "
                f"{retention_note(mime_type)}."
            }
        )
```

(b) After the blob fetch, before the image/PDF branch, add the video branch:

```python
    if mime_type.startswith("video/"):
        from src.agent.gemini_files import GeminiFileError, ensure_gemini_file_uri

        try:
            uri = ensure_gemini_file_uri(message_id, file_index, binary_data, mime_type)
        except GeminiFileError as e:
            return json.dumps({"error": f"Failed to prepare video for viewing: {e}"})
        return [
            {
                "type": "text",
                "text": f"Here is {file_name} ({mime_type}, {file_size} bytes) "
                f"from message {message_id}:",
            },
            {"type": "media", "file_uri": uri, "mime_type": mime_type},
        ]
```

Note: the video branch skips the eager `base64.b64encode` of the whole file — move the existing `file_base64 = base64.b64encode(...)` line *below* the video branch so a 100MB video isn't needlessly base64-encoded.

(c) Update the tool docstring: mention videos are supported and that expired media (videos 7 days, images 30 days) returns an error.

- [ ] **Step 3: Run tests** — targeted file, then `.venv/bin/pytest tests/unit -q` — expect PASS.

- [ ] **Step 4: Commit**

```bash
git add src/agent/tools/file_retrieval.py tests/unit/test_file_retrieval.py
git commit -m "feat(tools): retrieve_file supports videos and reports expired media"
```

---

### Task 7: History labeling + system prompt guidance

**Files:**
- Modify: `src/agent/history.py:104-126` (`simplify_mime_type`), `:20-40` (`FileMetadata` TypedDict), `:129-154` (`format_file_metadata`)
- Modify: `src/agent/agent.py:279-287` (files section of `_format_message_with_metadata`)
- Modify: `src/agent/prompts.py` (retrieve_file guidance, lines ~72 and ~398)
- Test: `tests/unit/test_history.py`

**Interfaces:**
- Consumes: `is_media_expired` (Task 3), `Message.created_at`.
- Produces: `FileMetadata` gains `expired: bool` (NotRequired); history metadata JSON gains `"expired": true` + `"note"` for expired files; `simplify_mime_type` returns `"video"` for `video/*`.

- [ ] **Step 1: Write failing tests** in `tests/unit/test_history.py`:

```python
class TestVideoHistoryMetadata:
    def test_simplify_video_mime(self):
        assert simplify_mime_type("video/mp4") == "video"
        assert simplify_mime_type("video/quicktime") == "video"

    def test_fresh_video_not_marked_expired(self, make_message):
        msg = make_message(files=[{"name": "a.mp4", "type": "video/mp4"}],
                           created_at=datetime.now() - timedelta(days=1))
        files = format_file_metadata(msg)
        assert "expired" not in files[0]

    def test_old_video_marked_expired(self, make_message):
        msg = make_message(files=[{"name": "a.mp4", "type": "video/mp4"}],
                           created_at=datetime.now() - timedelta(days=8))
        files = format_file_metadata(msg)
        assert files[0]["expired"] is True
```

(`make_message` = whatever factory/fixture the file already uses for `Message` objects; follow the existing tests.) Run — expect FAIL.

- [ ] **Step 2: Implement history changes.**

`simplify_mime_type` — add as the first branch:

```python
    if mime_type.startswith("video/"):
        return "video"
```

`FileMetadata` TypedDict — add:

```python
    expired: NotRequired[bool]  # Media past its retention window (not retrievable)
```

(import `NotRequired` from `typing`).

`format_file_metadata` — after building each entry:

```python
        entry = FileMetadata(
            name=name,
            type=simplify_mime_type(mime_type),
            message_id=msg.id,
            file_index=idx,
        )
        # NOTE: this flag flips once when the file crosses its retention
        # window — a one-time history byte change; acceptable for caching.
        if is_media_expired(mime_type, msg.created_at):
            entry["expired"] = True
        files.append(entry)
```

(import `is_media_expired` from `src.utils.media_retention` at module top).

`_format_message_with_metadata` (src/agent/agent.py:279) — extend the files comprehension:

```python
            meta_dict["files"] = [
                {
                    "name": f["name"],
                    "type": f["type"],
                    "id": f"{f['message_id']}:{f['file_index']}",
                    **({"expired": True} if f.get("expired") else {}),
                }
                for f in metadata["files"]
            ]
```

- [ ] **Step 3: Update the system prompt** (`src/agent/prompts.py`). Extend the `retrieve_file` tool description bullet (line ~72) and the usage example section (~398) with:

```
- Videos: a video is attached only on the turn it was uploaded. For follow-up
  questions about a video from an earlier message, call retrieve_file with its
  id from the history metadata to view it again.
- Retention: uploaded media is temporary — videos are kept 7 days, images 30
  days. Files marked "expired": true in history metadata have been cleaned up
  and CANNOT be retrieved; tell the user instead of calling retrieve_file.
```

- [ ] **Step 4: Run tests** — `.venv/bin/pytest tests/unit/test_history.py tests/unit/test_chat_agent_helpers.py -q` — expect PASS.

- [ ] **Step 5: Commit**

```bash
git add src/agent/history.py src/agent/agent.py src/agent/prompts.py tests/unit/test_history.py
git commit -m "feat(history): label expired media for the LLM and document video follow-ups"
```

---

### Task 8: Retention sweep job

**Files:**
- Modify: `src/utils/media_retention.py` (add sweep + thread)
- Modify: `src/db/models/message.py` (query helper)
- Modify: `src/app.py:~282` (start thread next to `start_dev_scheduler()`)
- Test: `tests/unit/test_media_retention.py`

**Interfaces:**
- Consumes: `blob_store.delete` / `make_blob_key`, `db.kv_get/kv_set`, `delete_cached_file_uri` (Task 4), `is_media_expired` (Task 3).
- Produces: `db.get_messages_with_files_before(cutoff: datetime) -> list[Message]`; `cleanup_expired_media() -> dict[str, int]` (returns `{"videos_deleted": n, "images_deleted": m}`); `run_media_cleanup_if_due() -> bool`; `start_media_cleanup_thread() -> None`.

- [ ] **Step 1: Write failing tests** (extend `tests/unit/test_media_retention.py`; use the test-DB fixtures the way `tests/unit/test_blob_store.py` does):

```python
class TestCleanupExpiredMedia:
    def _seed(self, db, blob_store, conversation_id, mime, days_old, data=b"blob"):
        """Insert a message with one file + blob, created days_old ago.

        Uses the existing conftest fixtures for user/conversation; reuse
        whatever fixture other tests use to get a conversation_id.
        """
        ext = "mp4" if mime.startswith("video/") else "png"
        msg = db.add_message(
            conversation_id,
            MessageRole.USER,
            "here is a file",
            files=[{"name": f"f.{ext}", "type": mime, "size": len(data)}],
        )
        backdated = (datetime.now() - timedelta(days=days_old)).isoformat()
        with db._pool.get_connection() as conn:
            conn.execute(
                "UPDATE messages SET created_at = ? WHERE id = ?", (backdated, msg.id)
            )
            conn.commit()
        blob_store.save(make_blob_key(msg.id, 0), data, mime)
        return msg.id

    def test_deletes_expired_video_blob(self, db, blob_store):
        msg_id = self._seed(db, blob_store, "video/mp4", days_old=8)
        counts = cleanup_expired_media()
        assert counts["videos_deleted"] == 1
        assert blob_store.get(make_blob_key(msg_id, 0)) is None

    def test_keeps_fresh_video(self, db, blob_store):
        msg_id = self._seed(db, blob_store, "video/mp4", days_old=3)
        cleanup_expired_media()
        assert blob_store.get(make_blob_key(msg_id, 0)) is not None

    def test_deletes_old_image_but_keeps_thumbnail(self, db, blob_store):
        msg_id = self._seed(db, blob_store, "image/png", days_old=31)
        blob_store.save(make_thumbnail_key(msg_id, 0), b"thumb", "image/jpeg")
        cleanup_expired_media()
        assert blob_store.get(make_blob_key(msg_id, 0)) is None
        assert blob_store.get(make_thumbnail_key(msg_id, 0)) is not None

    def test_image_between_windows_kept(self, db, blob_store):
        msg_id = self._seed(db, blob_store, "image/png", days_old=10)
        cleanup_expired_media()
        assert blob_store.get(make_blob_key(msg_id, 0)) is not None

    def test_idempotent(self, db, blob_store):
        self._seed(db, blob_store, "video/mp4", days_old=8)
        cleanup_expired_media()
        counts = cleanup_expired_media()
        assert counts == {"videos_deleted": 0, "images_deleted": 0}


class TestRunIfDue:
    def test_skips_when_ran_recently(self, db):
        db.kv_set("_system", "media_cleanup", "last_run", utcnow_naive().isoformat())
        assert run_media_cleanup_if_due() is False

    def test_runs_and_stamps_when_due(self, db):
        assert run_media_cleanup_if_due() is True
        assert db.kv_get("_system", "media_cleanup", "last_run") is not None
```

Fill in `_seed` concretely against the real model API (`db.add_message(...)` — check its signature in `src/db/models/message.py` — then `UPDATE messages SET created_at` via the connection pool, then `blob_store.save(make_blob_key(...), data, mime)`). Run — expect FAIL (functions missing).

- [ ] **Step 2: Implement the DB helper** in `src/db/models/message.py` (mirror the style of neighboring query methods):

```python
    def get_messages_with_files_before(self, cutoff: datetime) -> list[Message]:
        """Messages older than cutoff that have file attachments (for retention sweep)."""
        with self._pool.get_connection() as conn:
            rows = self._execute_with_timing(
                conn,
                """SELECT * FROM messages
                   WHERE files IS NOT NULL AND files != '[]' AND created_at < ?
                   ORDER BY created_at""",
                (cutoff.isoformat(),),
            ).fetchall()
            return [self._row_to_message(row) for row in rows]
```

(Use the same row→Message conversion the file already uses — grep `fromisoformat(row` in that file and reuse the existing helper/pattern.)

- [ ] **Step 3: Implement sweep + thread** in `src/utils/media_retention.py`:

```python
import json
import threading
from datetime import datetime, timedelta

CLEANUP_INTERVAL_SECONDS = 3600  # hourly tick; sweep runs at most daily
CLEANUP_MIN_PERIOD_HOURS = 24
_cleanup_thread: threading.Thread | None = None
_stop_event = threading.Event()


def cleanup_expired_media() -> dict[str, int]:
    """Delete expired media blobs and their Gemini URI cache entries.

    Thumbnails are intentionally kept so old conversations still render a
    placeholder. Idempotent: deleting an already-deleted blob is a no-op.
    """
    from src.agent.gemini_files import delete_cached_file_uri
    from src.db.blob_store import get_blob_store
    from src.db.models import db, make_blob_key

    counts = {"videos_deleted": 0, "images_deleted": 0}
    blob_store = get_blob_store()
    now = datetime.now()
    # Videos have the shortest window, so its cutoff bounds the scan
    cutoff = now - timedelta(days=Config.VIDEO_RETENTION_DAYS)

    for msg in db.get_messages_with_files_before(cutoff):
        for idx, file in enumerate(msg.files or []):
            mime_type = file.get("type", "")
            if not is_media_expired(mime_type, msg.created_at, now=now):
                continue
            if blob_store.delete(make_blob_key(msg.id, idx)):
                key = "videos_deleted" if mime_type.startswith("video/") else "images_deleted"
                counts[key] += 1
            if mime_type.startswith("video/"):
                delete_cached_file_uri(msg.id, idx)

    if counts["videos_deleted"] or counts["images_deleted"]:
        logger.info("Media retention sweep completed", extra=counts)
    return counts


def run_media_cleanup_if_due() -> bool:
    """Run the sweep if the last run was over CLEANUP_MIN_PERIOD_HOURS ago.

    The kv timestamp acts as a soft cross-worker lock: with 4 gunicorn
    workers ticking hourly, at most a couple race on the same day, and the
    sweep is idempotent so a duplicate run is harmless.
    """
    from src.db.models import db
    from src.utils.datetime_utils import utcnow_naive

    last_run = db.kv_get("_system", "media_cleanup", "last_run")
    if last_run:
        try:
            if datetime.fromisoformat(last_run) > utcnow_naive() - timedelta(
                hours=CLEANUP_MIN_PERIOD_HOURS
            ):
                return False
        except ValueError:
            pass
    db.kv_set("_system", "media_cleanup", "last_run", utcnow_naive().isoformat())
    cleanup_expired_media()
    return True


def _cleanup_loop() -> None:
    while not _stop_event.is_set():
        try:
            run_media_cleanup_if_due()
        except Exception:
            logger.error("Media cleanup sweep failed", exc_info=True)
        _stop_event.wait(CLEANUP_INTERVAL_SECONDS)


def start_media_cleanup_thread() -> None:
    """Start the daily media retention sweep (idempotent per process)."""
    global _cleanup_thread
    if _cleanup_thread is not None and _cleanup_thread.is_alive():
        return
    _cleanup_thread = threading.Thread(
        target=_cleanup_loop, daemon=True, name="media-cleanup"
    )
    _cleanup_thread.start()
    logger.info("Media cleanup thread started")
```

Add `logger = get_logger(__name__)` + import at top if not present.

- [ ] **Step 4: Start the thread at app startup.** In `src/app.py`, right after the `start_dev_scheduler()` block (~line 284):

```python
    from src.utils.media_retention import start_media_cleanup_thread

    start_media_cleanup_thread()
```

(Unlike the dev scheduler this runs in all environments — production has no systemd timer for media cleanup.)

- [ ] **Step 5: Run tests** — `.venv/bin/pytest tests/unit/test_media_retention.py -v`, then full `tests/unit -q` — expect PASS.

- [ ] **Step 6: Commit**

```bash
git add src/utils/media_retention.py src/db/models/message.py src/app.py tests/unit/test_media_retention.py
git commit -m "feat(retention): daily sweep deletes expired videos and images"
```

---

### Task 9: 410 Gone for expired media on file routes

**Files:**
- Modify: `src/api/errors.py` (ErrorCode + helper)
- Modify: `src/api/routes/files.py` (`get_message_file`, ~line 263)
- Test: `tests/integration/test_routes_files.py`

**Interfaces:**
- Consumes: `is_media_expired` (Task 3).
- Produces: `ErrorCode.GONE`, `raise_gone_error(message: str) -> NoReturn`; `GET /api/messages/<id>/files/<idx>` returns 410 for expired media.

- [ ] **Step 1: Write failing integration tests** in `tests/integration/test_routes_files.py` (reuse its message-seeding fixtures; backdate `created_at` via direct SQL as in Task 8):

```python
class TestExpiredMediaGone:
    def test_expired_video_returns_410(self, client, auth_headers, seeded_old_video):
        resp = client.get(
            f"/api/messages/{seeded_old_video}/files/0", headers=auth_headers
        )
        assert resp.status_code == 410

    def test_fresh_video_returns_200(self, client, auth_headers, seeded_fresh_video):
        resp = client.get(
            f"/api/messages/{seeded_fresh_video}/files/0", headers=auth_headers
        )
        assert resp.status_code == 200
        assert resp.mimetype == "video/mp4"

    def test_old_pdf_still_served(self, client, auth_headers, seeded_old_pdf):
        resp = client.get(
            f"/api/messages/{seeded_old_pdf}/files/0", headers=auth_headers
        )
        assert resp.status_code == 200
```

Run — expect FAIL (200 or 404 instead of 410).

- [ ] **Step 2: Implement.** `src/api/errors.py` — add to `ErrorCode` (Resource errors group):

```python
    GONE = "GONE"  # Resource expired per retention policy
```

and next to `raise_not_found_error`:

```python
def raise_gone_error(message: str) -> NoReturn:
    """Raise a gone error (410) for media past its retention window."""
    raise APIError(410, ErrorCode.GONE, message)
```

`src/api/routes/files.py` `get_message_file` — after the file-metadata lookup (`file_type` is known, ~line 322):

```python
    from src.utils.media_retention import is_media_expired, retention_note

    if is_media_expired(file_type, message.created_at):
        raise_gone_error(f"This file has been cleaned up. {retention_note(file_type)}.")
```

(Move imports to module top; add `raise_gone_error` to the existing errors import. Register 410 in the route's `@api.doc(responses=[...])` list.)

- [ ] **Step 3: Run tests** — `.venv/bin/pytest tests/integration/test_routes_files.py -v` — expect PASS. Also run `.venv/bin/pytest tests/integration/test_openapi.py -q` (schema changed).

- [ ] **Step 4: Commit**

```bash
git add src/api/errors.py src/api/routes/files.py tests/integration/test_routes_files.py
git commit -m "feat(files): return 410 Gone for media past retention"
```

---

### Task 10: Frontend video rendering (playback + expired state)

**Files:**
- Modify: `web/src/components/messages/attachments.ts` (`renderMessageFiles`)
- Modify: `web/src/api/client.ts` (blob fetch helper — check first whether `file-actions.ts`/`client.ts` already has an authenticated file-download fetch to reuse; grep `files/` in `web/src/api/client.ts` and `web/src/core/file-actions.ts`)
- Modify: `web/src/styles/components/messages.css` (`.message-video` styles)
- Test: covered by Task 12 E2E; type-check via `cd web && npx tsc --noEmit`

**Interfaces:**
- Consumes: `GET /api/messages/<id>/files/<idx>` (Bearer auth, 410 when expired), `FileMetadata.previewUrl` (set for videos since Task 2).
- Produces: videos render as a click-to-load player; expired videos render a disabled chip.

**Design constraint:** JWT rides the `Authorization` header, so `<video src="/api/...">` would 401. Playback = authenticated `fetch` → `Blob` → `URL.createObjectURL` → `<video>`. Videos are ≤100MB short clips; loading fully into a blob is acceptable (matches lightbox/thumbnail patterns).

- [ ] **Step 1: Add a blob fetch helper** (reuse if one exists). In `web/src/api/client.ts`, following the auth-header pattern of `fetchThumbnail` (~line 416):

```typescript
/** Fetch a message file as a Blob (for video playback / downloads). Throws on non-OK; error has status. */
export async function fetchFileBlob(messageId: string, fileIndex: number): Promise<Blob> {
  const token = getToken();
  const response = await fetch(`/api/messages/${messageId}/files/${fileIndex}`, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  });
  if (!response.ok) {
    const error = new Error(`File fetch failed: ${response.status}`) as Error & {
      status: number;
    };
    error.status = response.status;
    throw error;
  }
  return response.blob();
}
```

(Match the module's actual token-getter name and export style. If `file-actions.ts` already downloads files this way, extract/reuse instead of duplicating.)

- [ ] **Step 2: Render videos in `attachments.ts`.** In `renderMessageFiles`, split out videos before the images/documents split:

```typescript
  const videos = files.filter((f) => f.type.startsWith('video/'));
  const images = files.filter((f) => f.type.startsWith('image/'));
  const documents = files.filter(
    (f) => !f.type.startsWith('image/') && !f.type.startsWith('video/')
  );
```

Add rendering after the images gallery:

```typescript
  videos.forEach((file) => {
    const fileIndex = files.indexOf(file);
    container.appendChild(
      renderVideoAttachment(file, file.messageId || messageId, file.fileIndex ?? fileIndex)
    );
  });
```

New function in the same file:

```typescript
function renderVideoAttachment(
  file: FileMetadata,
  messageId: string,
  fileIndex: number
): HTMLElement {
  const wrapper = document.createElement('div');
  wrapper.className = 'message-video';

  // Just-uploaded file: play directly from the local blob URL
  if (file.previewUrl) {
    wrapper.appendChild(createVideoElement(file.previewUrl));
    return wrapper;
  }

  // Historical file: click-to-load via authenticated fetch
  const button = document.createElement('button');
  button.className = 'message-video-load';
  button.innerHTML = `${getFileIcon(file.type)} <span>${escapeHtml(file.name)}</span><span class="video-load-hint">Tap to load</span>`;
  button.addEventListener('click', async () => {
    button.disabled = true;
    button.querySelector('.video-load-hint')!.textContent = 'Loading…';
    try {
      const blob = await fetchFileBlob(messageId, fileIndex);
      const video = createVideoElement(URL.createObjectURL(blob));
      wrapper.replaceChildren(video);
      void video.play();
    } catch (error) {
      const status = (error as { status?: number }).status;
      button.classList.add('expired');
      button.querySelector('.video-load-hint')!.textContent =
        status === 410 ? 'Video expired (videos are kept 7 days)' : 'Failed to load video';
    }
  });
  wrapper.appendChild(button);
  return wrapper;
}

function createVideoElement(src: string): HTMLVideoElement {
  const video = document.createElement('video');
  video.className = 'message-video-player';
  video.controls = true;
  video.playsInline = true;
  video.preload = 'metadata';
  video.src = src;
  return video;
}
```

(Import `fetchFileBlob`. Temp-id messages: `messageId.startsWith('temp-')` files always have `previewUrl`, so the fetch path is safe.)

- [ ] **Step 3: Styles** — append to `web/src/styles/components/messages.css`:

```css
/* Video attachments */
.message-video {
    margin-top: var(--space-2);
    max-width: 400px;
}

.message-video-player {
    width: 100%;
    max-height: 300px;
    border-radius: var(--radius-md);
    background: #000;
}

.message-video-load {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    padding: var(--space-2) var(--space-3);
    background: var(--bg-secondary);
    border: 1px solid var(--border);
    border-radius: var(--radius-md);
    color: var(--text-primary);
    cursor: pointer;
}

.message-video-load .video-load-hint {
    color: var(--text-secondary);
    font-size: var(--font-size-sm);
}

.message-video-load.expired {
    opacity: 0.6;
    cursor: default;
}
```

- [ ] **Step 4: Verify** — `cd web && npx tsc --noEmit && npx vitest run` — expect PASS. Then `make dev`, upload a small video in the browser, confirm the pending chip, send (mock or real), and playback of the just-sent video.

- [ ] **Step 5: Commit**

```bash
git add web/src/components/messages/attachments.ts web/src/api/client.ts web/src/styles/components/messages.css
git commit -m "feat(web): render video attachments with tap-to-load playback and expired state"
```

---

### Task 11: Fix upload-progress layout break on mobile (TDD)

**Files:**
- Modify: `web/src/styles/components/input.css:321-377` (likely) — actual fix depends on diagnosis
- Test: `web/tests/e2e/chat.spec.ts` (new test in the "Chat - Upload Progress" describe block)

**Interfaces:** none (CSS-only + test).

**Context:** User reports the "Uploading" indicator breaks the input box layout on mobile. `.upload-progress` is a sibling strip above `.input-container`, glued via sibling selectors (`input.css:368-377`). Use superpowers:systematic-debugging: reproduce first, then fix the root cause — do not guess-patch.

- [ ] **Step 1: Write the failing E2E test** (mobile viewport, in the existing "Chat - Upload Progress" describe block — follow its helpers for attaching a file and triggering send):

```typescript
test('upload progress does not break input layout on mobile', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  // ...existing helper steps to attach a file and reveal #upload-progress...
  await page.evaluate(() => {
    document.getElementById('upload-progress')?.classList.remove('hidden');
  });
  const progress = page.locator('#upload-progress');
  const inputContainer = page.locator('.input-container');
  const progressBox = await progress.boundingBox();
  const inputBox = await inputContainer.boundingBox();
  // The strip must align with the input container it visually attaches to
  expect(Math.abs(progressBox!.x - inputBox!.x)).toBeLessThan(2);
  expect(Math.abs(progressBox!.width - inputBox!.width)).toBeLessThan(2);
  // And must not cause horizontal page overflow
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - window.innerWidth
  );
  expect(overflow).toBeLessThanOrEqual(0);
});
```

Run: `cd web && timeout 600 npx playwright test -g "upload progress does not break"`
Expected: FAIL, reproducing the user's report. **If it passes**, the assertions don't capture the break — open `make dev` at 390px, show the strip, screenshot, and adjust assertions to match the actual defect (e.g. border-radius mismatch, strip rendering below the input) before touching CSS.

- [ ] **Step 2: Diagnose.** Inspect computed layout at 390px (Playwright `--debug` or browser devtools): compare `.upload-progress` margins/width against `.input-container` and check the mobile media queries in `input.css` for margins/padding applied to `.input-container` but not to `.upload-progress`. Identify the one root cause before editing.

- [ ] **Step 3: Fix.** Likely shape of the fix (adjust to diagnosis) — make the strip inherit the same horizontal geometry as the input container inside the mobile breakpoint:

```css
@media (max-width: 768px) {
    .upload-progress {
        margin: 0 var(--space-3); /* match .input-container's mobile margins */
    }
}
```

- [ ] **Step 4: Verify** — the new test passes at 390px; re-run the full upload-progress describe block on desktop viewport too: `cd web && timeout 600 npx playwright test -g "Upload Progress"`. Expected: all PASS. Visually confirm both viewports in `make dev`.

- [ ] **Step 5: Commit**

```bash
git add web/src/styles/components/input.css web/tests/e2e/chat.spec.ts
git commit -m "fix(web): align upload progress strip with input container on mobile"
```

---

### Task 12: E2E video upload flow

**Files:**
- Create: `web/tests/e2e/fixtures/tiny.mp4` (generated, ~1KB)
- Modify: `web/tests/e2e/chat.spec.ts` (new describe block "Chat - Video Upload")
- Possibly modify the E2E mock server (wherever the "Chat - Clipboard Paste" tests get their mocked chat response — follow that infrastructure)

**Interfaces:**
- Consumes: file input `#file-input` (accept from Task 2), pending chip rendering, video attachment rendering (Task 10).

- [ ] **Step 1: Create the fixture** — a minimal mp4 that passes both browser MIME sniffing and backend libmagic:

```bash
python3 - <<'EOF'
data = (
    b"\x00\x00\x00\x20ftypisom\x00\x00\x02\x00isomiso2avc1mp41"
    + b"\x00\x00\x00\x08free"
    + b"\x00\x00\x00\x10mdat" + b"\x00" * 8
)
with open("web/tests/e2e/fixtures/tiny.mp4", "wb") as f:
    f.write(data)
EOF
python3 -c "import magic; print(magic.from_file('web/tests/e2e/fixtures/tiny.mp4', mime=True))"
```

Expected output: `video/mp4`. (If the fixtures directory differs — check where existing E2E fixtures live first — put it beside them and adjust paths.)

- [ ] **Step 2: Write the E2E test** (model the setup — login/mock/waits — on the "Chat - Clipboard Paste" describe block):

```typescript
test.describe('Chat - Video Upload', () => {
  test('user can attach and send a video', async ({ page }) => {
    // ...standard setup from neighboring tests...
    await page
      .locator('#file-input')
      .setInputFiles('tests/e2e/fixtures/tiny.mp4');
    // Pending chip appears with the file name
    await expect(page.locator('.file-preview')).toContainText('tiny.mp4');
    await page.locator('#message-input').fill('what is in this video?');
    // ...send + mocked response per the block's existing pattern...
    // The sent user message renders a video attachment (local preview)
    await expect(page.locator('.message-video video')).toBeVisible();
  });

  test('oversized video is rejected with a toast', async ({ page }) => {
    // Shrink the server-driven limit below the fixture size via route mock
    await page.route('**/api/config/upload', async (route) => {
      const response = await route.fetch();
      const json = await response.json();
      json.maxVideoFileSize = 10; // bytes — smaller than tiny.mp4
      await route.fulfill({ response, json });
    });
    // ...standard setup/reload from neighboring tests so the config is re-fetched...
    await page
      .locator('#file-input')
      .setInputFiles('tests/e2e/fixtures/tiny.mp4');
    await expect(page.locator('.toast')).toContainText('exceeds');
    // Nothing was added to the pending preview
    await expect(page.locator('.file-preview')).not.toContainText('tiny.mp4');
  });
});
```

(Adjust the toast selector to whatever class `Toast.ts` renders — check an existing toast assertion in the spec file.)

- [ ] **Step 3: Run** — `cd web && timeout 600 npx playwright test -g "Video Upload"` — expect PASS. Zero tolerance for flakiness: if it flakes, find the root cause (use the e2e-debugger agent).

- [ ] **Step 4: Commit**

```bash
git add web/tests/e2e/fixtures/tiny.mp4 web/tests/e2e/chat.spec.ts
git commit -m "test(e2e): cover video upload flow"
```

---

### Task 13: Docs, TODO, and final verification

**Files:**
- Modify: `docs/features/file-handling.md` (new "Video Uploads" section)
- Modify: `TODO.md` (deferred items)
- Modify: `CLAUDE.md`/`AGENTS.md` only if the docs-updater agent deems it necessary
- Verify: `.env.example` (done in Task 1 — confirm)

- [ ] **Step 1: Document the feature** in `docs/features/file-handling.md` — a "Video Uploads" section covering: supported types + 100MB limit, Gemini Files API bridge + kv cache (47h TTL, `_system`/`gemini_files`), on-demand follow-ups via `retrieve_file`, retention policy (7d/30d, thumbnails kept, daily sweep thread, `_system`/`media_cleanup` lock), 410 endpoint behavior, tap-to-load playback (auth-header constraint), and key files. Follow the section format used elsewhere in that file (How it works / Configuration / Key Files / Testing).

- [ ] **Step 2: Record deferred work** in `TODO.md`:

```markdown
## Video uploads — deferred
- Multipart streaming upload endpoint (approach B in the 2026-07-19 spec) — revisit if base64 JSON memory spikes or >100MB clips become a real problem
- Video poster-frame thumbnails (requires ffmpeg on the server)
- Sweep scan optimization: track last-swept cutoff instead of rescanning all old messages daily (fine at current scale)
```

- [ ] **Step 3: Full verification**

```bash
make lint
make test-all
cd web && timeout 600 npx playwright test
```

Expected: all PASS. Fix anything that fails before committing.

- [ ] **Step 4: Commit**

```bash
git add docs/features/file-handling.md TODO.md
git commit -m "docs(files): document video uploads and media retention"
```

- [ ] **Step 5: Run the docs-updater agent** (per CLAUDE.md workflow) to catch anything the manual docs pass missed, and the code-reviewer agent over the whole feature branch diff.
