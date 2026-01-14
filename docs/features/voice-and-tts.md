# Voice and Text-to-Speech

This document covers voice input (speech-to-text) and text-to-speech (TTS) features.

## Voice Input

Voice input uses the Web Speech API (`SpeechRecognition`) in [VoiceInput.ts](../../web/src/components/VoiceInput.ts).

### Browser Support

- **Chrome/Edge**: Uses Google's cloud servers (requires internet, may fail with `network` error behind VPNs/firewalls)
- **Safari (iOS 14.5+/macOS)**: Uses on-device Siri speech recognition (works offline)
- **Firefox**: Not supported (button is hidden)

### Features

- The button shows a pulsing red indicator while recording
- Transcribed text is appended to the textarea in real-time
- **Auto-stop on send**: Voice recording is automatically stopped when a message is sent (via `stopVoiceRecording()` in `sendMessage()`), preventing transcribed text from being re-added to the cleared input

### Language Selection

Long-press (500ms) on the microphone button to open a language selector popup.

- Currently supports English (en-US) and Czech (cs-CZ)
- The browser's preferred language is shown first if supported
- The selected language is persisted to localStorage

### Key Files

- [VoiceInput.ts](../../web/src/components/VoiceInput.ts) - Voice input component
- [messaging.ts](../../web/src/core/messaging.ts) - `stopVoiceRecording()` integration
- [icons.ts](../../web/src/utils/icons.ts) - Microphone icons

## Text-to-Speech (TTS)

Assistant messages can be read aloud using the Web Speech API (`SpeechSynthesis`). A speaker icon button appears in the message actions for assistant messages.

### How it works

1. **Language detection**: The LLM includes an ISO 639-1 language code (e.g., "en", "cs") in the metadata block of every response
2. **Language storage**: The language is stored in the `messages.language` column in the database
3. **Voice selection**: When the speak button is clicked, `findVoiceForLanguage()` finds a voice matching the message's language
4. **TTS playback**: Uses `SpeechSynthesisUtterance` with the selected voice and language

### Browser Support

- **Chrome/Edge**: Voices load asynchronously (`voiceschanged` event). Good selection of voices.
- **Safari (iOS/macOS)**: Uses system voices including Siri voices. Good Czech support.
- **Firefox**: Supported but limited voice selection.
- **Unsupported browsers**: Button is hidden entirely (no disabled state).

### Content Filtering

The `getTextContentForTTS()` function excludes from reading:
- Thinking indicator content (`.thinking-indicator`)
- Inline copy buttons (`.inline-copy-btn`)
- Code language labels (`.code-language`)
- File attachment metadata (`.message-files`)
- Copyable header elements (`.copyable-header`)

### Toggle Behavior

- Click the speak button to start reading - button transforms to red pulsing stop icon
- Click stop button to stop reading - button transforms back to speaker icon
- Starting a new message's speech automatically stops the current one

### Language Migration

For existing messages without language data:
- Migration `0017_detect_message_languages.py` uses `langdetect` library
- Processes assistant messages in batches
- Detects and stores ISO 639-1 language codes

### Key Files

- [tts.ts](../../web/src/core/tts.ts) - `speakMessage()`, `findVoiceForLanguage()`, `initTTSVoices()`, `getTextContentForTTS()`
- [messages/actions.ts](../../web/src/components/messages/actions.ts) - Speak button in `createMessageActions()`
- [utils.py](../../src/api/utils.py) - `extract_language_from_metadata()`
- [prompts.py](../../src/agent/prompts.py) - System prompt requiring language in metadata
- [messages.css](../../web/src/styles/components/messages.css) - `.message-speak-btn` styles
- [icons.ts](../../web/src/utils/icons.ts) - `SPEAKER_ICON`, `STOP_ICON`

## See Also

- [UI Features](ui-features.md) - Input toolbar, microphone button
- [Chat and Streaming](chat-and-streaming.md) - Metadata extraction
