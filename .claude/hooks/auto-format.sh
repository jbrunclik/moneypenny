#!/bin/bash
# Auto-format files after Edit/Write tool calls
# Called by Claude Code PostToolUse hook for Edit|Write
INPUT=$(cat)
FILE_PATH=$(echo "$INPUT" | jq -r '.tool_input.file_path // empty')
[ -z "$FILE_PATH" ] && exit 0

if [[ "$FILE_PATH" == *.py ]]; then
  cd "$CLAUDE_PROJECT_DIR" || exit 0
  if [ ! -x .venv/bin/ruff ]; then
    echo "auto-format: .venv/bin/ruff not found - run make setup" >&2
    exit 1
  fi
  .venv/bin/ruff format -q "$FILE_PATH"
  # F401 stays unfixable: an import added one edit before its first use
  # would otherwise be deleted in between
  .venv/bin/ruff check -q --fix --unfixable F401 --exit-zero "$FILE_PATH" > /dev/null
elif [[ "$FILE_PATH" == *.ts || "$FILE_PATH" == *.tsx ]]; then
  cd "$CLAUDE_PROJECT_DIR/web" || exit 0
  npx eslint --fix "$FILE_PATH" > /dev/null 2>&1
fi
exit 0
