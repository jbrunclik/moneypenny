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

Dictation starts in the conversation's language (Nov 17 2026,
`languageForRecording()`): the latest message's detected `language`
(`data-language` on the message element), when dictation supports it.
Long-press (500ms) on the microphone button opens a language selector popup;
a pick there wins for that conversation, and otherwise (a new chat, an
unsupported language) the saved pick or the browser's language applies.

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

`getSpeechChunks()` reads prose only (Nov 17 2026): it drops UI chrome
(thinking indicator, copy buttons, code labels, attachments), code blocks,
tables, diagrams, formulas, artifacts, citation marks and the grounding note,
and strips inline citation numbers ("[1]") and bare links. Each paragraph,
list item or heading is its own utterance (queued; a chunk over 240 characters
is split at sentence ends), since some voices stop a long utterance after
~15 s and the pauses read more naturally. Stop cancels the whole queue.

### Toggle Behavior

- Click the speak button to start reading - button transforms to red pulsing stop icon
- Click stop button to stop reading - button transforms back to speaker icon
- Starting a new message's speech automatically stops the current one

### Detected Languages

The reply's `language` is detected only among `LANGDETECT_LANGUAGES` (default
`cs,en`; langdetect profile codes, at least two, checked at startup). Text in
any other language comes back as the closest configured one, so its voice is
wrong - add the code when a new language is in real use. Each profile costs
~1 MB per worker; langdetect's own `detect()` loads all 55 (~55 MB per worker,
found by the Oct 2026 memory profiling), which is why `detect_response_language`
builds its own factory.

### Language Migration

For existing messages without language data:
- Migration `0017_detect_message_languages.py` uses `langdetect` library
- Processes assistant messages in batches
- Detects and stores ISO 639-1 language codes

### Key Files

- [tts.ts](../../web/src/core/tts.ts) - `speakMessage()`, `findVoiceForLanguage()`, `initTTSVoices()`, `getSpeechChunks()`
- [messages/actions.ts](../../web/src/components/messages/actions.ts) - Speak button in `createMessageActions()`
- [content.py](../../src/agent/content.py) - `detect_response_language()` (server-side langdetect on the reply)
- [prompt_texts/core.py](../../src/agent/prompt_texts/core.py) - System prompt text
- [messages.css](../../web/src/styles/components/messages.css) - `.message-speak-btn` styles
- [icons.ts](../../web/src/utils/icons.ts) - `SPEAKER_ICON`, `STOP_ICON`

## See Also

- [Composer](ui-composer.md) - Input toolbar, microphone button
- [Thinking Indicator and Source Chips](thinking-and-sources.md) - response metadata (sources) and the streamed trace
