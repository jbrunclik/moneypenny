#!/bin/bash
# Auto-format files after Edit/Write tool calls
# Called by Claude Code PostToolUse hook for Edit|Write
INPUT=$(cat)
FILE_PATH=$(echo "$INPUT" | jq -r '.tool_input.file_path // empty')
[ -z "$FILE_PATH" ] && exit 0

if [[ "$FILE_PATH" == *.py ]]; then
  cd "$CLAUDE_PROJECT_DIR"
  .venv/bin/ruff format "$FILE_PATH" 2>/dev/null
  .venv/bin/ruff check "$FILE_PATH" --fix 2>/dev/null
elif [[ "$FILE_PATH" == *.ts || "$FILE_PATH" == *.tsx ]]; then
  cd "$CLAUDE_PROJECT_DIR/web"
  npx eslint --fix "$FILE_PATH" 2>/dev/null
fi
exit 0
