"""Verification script: ensure manage_memory-only tool calls produce a text response.

Usage:
    python -m scripts.test_memory_stream

Requires GEMINI_API_KEY in .env. Instantiates ChatAgent directly and streams
a "remember my favorite color" message, verifying that:
1. tool_start for manage_memory is present
2. tool_end for manage_memory is present
3. Final event has non-empty text in result_messages
"""

import sys
from pathlib import Path

from dotenv import load_dotenv

# Ensure project root is on sys.path before importing project modules
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
load_dotenv()


def main() -> None:
    from src.agent.agent import ChatAgent
    from src.config import Config

    if not Config.GEMINI_API_KEY:
        print("ERROR: GEMINI_API_KEY not set in .env")
        sys.exit(1)

    agent = ChatAgent(model_name=Config.DEFAULT_MODEL, include_thoughts=True)

    events: list[dict] = []
    print("Streaming: 'Remember that my favorite color is blue'...")

    for event in agent.stream_chat_events(
        message="Remember that my favorite color is blue",
        files=None,
        history=[],
        user_name="TestUser",
        user_id="test-user-id",
    ):
        events.append(event)
        event_type = event.get("type", "?")
        if event_type == "token":
            print(event.get("text", ""), end="", flush=True)
        elif event_type in ("tool_start", "tool_end"):
            print(f"\n[{event_type}] {event.get('tool', '')}")
        elif event_type == "final":
            print(f"\n[final] content length: {len(event.get('content', ''))}")

    # Verify
    tool_starts = [
        e for e in events if e.get("type") == "tool_start" and e.get("tool") == "manage_memory"
    ]
    tool_ends = [
        e for e in events if e.get("type") == "tool_end" and e.get("tool") == "manage_memory"
    ]
    finals = [e for e in events if e.get("type") == "final"]

    ok = True
    if not tool_starts:
        print("\nFAIL: No tool_start for manage_memory")
        ok = False
    else:
        print(f"\nOK: {len(tool_starts)} tool_start(s) for manage_memory")

    if not tool_ends:
        print("FAIL: No tool_end for manage_memory")
        ok = False
    else:
        print(f"OK: {len(tool_ends)} tool_end(s) for manage_memory")

    if not finals:
        print("FAIL: No final event")
        ok = False
    else:
        final = finals[-1]
        content = final.get("content", "")
        result_messages = final.get("result_messages", [])
        if content.strip():
            print(f"OK: Final content has {len(content)} chars")
        else:
            print("FAIL: Final content is empty")
            ok = False
        if result_messages:
            print(f"OK: {len(result_messages)} result_messages")
        else:
            print("FAIL: No result_messages")
            ok = False

    print(f"\n{'PASSED' if ok else 'FAILED'}")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
