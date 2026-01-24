# Streaming Metadata Handling

This document describes how the chat agent handles metadata blocks during streaming, known issues, and debugging guidance.

## Overview

The streaming system uses HTML comment markers to embed metadata in messages:

- **MSG_CONTEXT**: `<!-- MSG_CONTEXT: {...} -->` - History context injected into messages sent to the LLM
- **METADATA**: `<!-- METADATA: {...} -->` - Response metadata appended by the LLM (sources, language, etc.)

These markers must be stripped during streaming to avoid:
1. Echoing history context back to the user
2. Showing raw metadata blocks in the UI
3. **Critical**: Unclosed `<!--` causing browsers to hide content as HTML comments

## The Malformed METADATA Bug (January 2025)

### Symptoms

- Messages stream correctly to the client
- After page reload, messages appear **empty**
- Database contains content starting with `<!-- METADATA: {"language": "cs"}Actual content...`
- Browser interprets unclosed `<!--` as HTML comment start, hiding everything after it

### Root Cause

When the LLM outputs METADATA immediately after MSG_CONTEXT ends (in the same chunk), without proper closing `-->`:

```
Chunk: ...} -->\n<!-- METADATA: {"language": "cs"}Aha, chápu...
       ↑ MSG_CONTEXT ends    ↑ METADATA starts (no closing -->)
```

**Bug in original code:**
1. MSG_CONTEXT was stripped, leaving `<!-- METADATA: {"language": "cs"}Aha, chápu...`
2. This was added to `full_response`
3. METADATA marker was detected, but no closing `-->` found
4. Code set `in_metadata = True` and cleared `buffer`
5. **But forgot to strip the incomplete METADATA from `full_response`!**
6. Stream ended, malformed content was stored in database

### The Fix

Strip from `full_response` when **entering** `in_metadata` mode, not just when exiting:

```python
# In stream_chat_events, when METADATA starts but doesn't close:
in_metadata = True
buffer = ""
# Strip incomplete METADATA from full_response NOW
fr_marker_idx = full_response.rfind(metadata_marker)
if fr_marker_idx != -1:
    full_response = full_response[:fr_marker_idx]
```

Also added backup defense in `extract_metadata_from_response()`:

```python
MALFORMED_METADATA_START_PATTERN = re.compile(
    r"^<!--\s*METADATA:\s*\{[^}]*\}(?!\s*\n\s*-->)(?!\s*-->)",
    re.IGNORECASE,
)
```

## Debugging Guide

### Check if this bug has recurred

1. **Symptom**: Message appears empty after reload but streamed correctly

2. **Check database content**:
   ```sql
   SELECT content FROM messages WHERE id = 'message-id';
   ```
   Look for content starting with `<!-- METADATA:` without closing `-->`

3. **Check server logs** for the streaming session:
   ```
   grep "METADATA" /var/log/ai-chatbot/app.log | grep "chunk"
   ```
   Look for:
   - `"Response metadata at start of output"` warning
   - Chunk content showing METADATA immediately after MSG_CONTEXT

### Key log entries

```python
# Warning when METADATA appears suspiciously early
logger.warning(
    "Response metadata at start of output - model may have skipped content",
    extra={"marker_pos": marker_pos, "buffer_length": len(buffer), "chunk_count": chunk_count},
)

# Info when MSG_CONTEXT block handling
logger.info("MSG_CONTEXT block ended (multi-chunk)")
logger.info("Stripped echoed MSG_CONTEXT from output")

# Info when content found after METADATA
logger.info("Content found after metadata block", extra={"remaining_len": len(remaining)})
```

### Manual fix for corrupted messages

If messages are already corrupted in the database:

```sql
-- Find corrupted messages
SELECT id, content FROM messages
WHERE content LIKE '<!-- METADATA:%'
AND content NOT LIKE '%-->%';

-- Fix by stripping malformed METADATA prefix
-- Pattern: <!-- METADATA: {simple JSON}Content...
UPDATE messages
SET content = REGEXP_REPLACE(content, '^<!--\s*METADATA:\s*\{[^}]*\}', '')
WHERE id = 'corrupted-message-id';
```

## State Machine

The streaming processor maintains these states:

```
┌─────────────────┐
│   in_msg_context = False    │
│   in_metadata = False       │
└──────────┬──────────────────┘
           │
           ▼ (MSG_CONTEXT marker found, no -->)
┌─────────────────┐
│   in_msg_context = True     │◄─────┐
│   in_metadata = False       │      │ (no --> yet)
└──────────┬──────────────────┘      │
           │ (--> found)             │
           ├─────────────────────────┘
           ▼
┌─────────────────┐
│   in_msg_context = False    │
│   in_metadata = False       │
└──────────┬──────────────────┘
           │
           ▼ (METADATA marker found, no -->)
┌─────────────────┐
│   in_msg_context = False    │◄─────┐
│   in_metadata = True        │      │ (no --> yet)
│   [full_response stripped]  │      │
└──────────┬──────────────────┘      │
           │ (--> found)             │
           ├─────────────────────────┘
           ▼
┌─────────────────┐
│   in_msg_context = False    │
│   in_metadata = False       │
│   [remaining content added] │
└─────────────────────────────┘
```

## Known Limitations

### 1. `-->` in JSON values

If MSG_CONTEXT or METADATA JSON contains literal `-->`, parsing breaks:

```
<!-- MSG_CONTEXT: {"summary": "Used --> operator"} -->
                              ↑ Would match here instead of end
```

**Mitigation**: `json.dumps()` doesn't produce raw `-->` in output. This would only occur with unusual user content or tool results.

### 2. Nested markers

Malformed input with nested markers (e.g., METADATA containing MSG_CONTEXT marker) would parse incorrectly. This should never occur in practice.

## Related Files

- `src/agent/agent.py` - `stream_chat_events()` method (lines 552-964)
- `src/agent/content.py` - `extract_metadata_from_response()`, `MALFORMED_METADATA_START_PATTERN`
- `tests/unit/test_chat_agent_helpers.py` - `TestStreamingMetadataBlockHandling` class

## Commits

- `4a8a334` - Initial fix: use distinct markers for history context vs response metadata
- `2175ae9` - Fix: strip incomplete METADATA from full_response when entering metadata mode
