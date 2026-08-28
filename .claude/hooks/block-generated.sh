#!/usr/bin/env bash
# PreToolUse (Edit|Write): block hand-edits to generated files.
# Generated artifacts must be regenerated from their source, never edited directly.
# Exit 2 tells Claude Code to block the tool call and feeds stderr back to the model.
set -euo pipefail

input="$(cat)"
fp="$(printf '%s' "$input" | jq -r '.tool_input.file_path // empty' 2>/dev/null || true)"
[ -z "$fp" ] && exit 0

case "$fp" in
  */web/src/types/generated-api.ts)
    echo "Refusing to edit a generated file: web/src/types/generated-api.ts" >&2
    echo "It is generated from the OpenAPI spec. Run 'make types' to regenerate it, and put hand-written types in web/src/types/api.ts instead." >&2
    exit 2
    ;;
  */static/openapi.json)
    echo "Refusing to edit a generated file: static/openapi.json" >&2
    echo "It is exported from the backend. Run 'make openapi' to regenerate it; change the Pydantic schemas in src/api/schemas.py instead." >&2
    exit 2
    ;;
esac

exit 0
