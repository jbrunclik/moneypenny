# Language Learning

Language Learning allows users to create dedicated language programs where an AI tutor helps them learn any language through assessments, lessons, and interactive quizzes.

## Overview

Each language program gets its own conversation with a specialized system prompt that instructs the AI to act as a language tutor. The AI uses KV storage to persist learner data (profile, assessment, vocabulary, grammar, weak points, session history) across sessions. All quiz evaluation is done by the LLM, not client-side.

## Architecture

### Database

Language conversations use two columns on the `conversations` table:
- `is_language INTEGER DEFAULT 0` - Flags language conversations
- `language_program TEXT DEFAULT NULL` - Program slug (e.g., "spanish")

These are added by migration `0032_add_language_learning.py`. Language conversations are excluded from the main conversation list and FTS search.

### API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/language/programs` | GET | List user's language programs |
| `/api/language/programs` | POST | Create a new program |
| `/api/language/programs/<id>` | DELETE | Delete program + conversation + KV data |
| `/api/language/<program>/conversation` | GET | Get or create program's conversation |
| `/api/language/<program>/reset` | POST | Reset conversation (clear messages) |

### KV Storage

Namespace: `language`

| Key | Description |
|-----|-------------|
| `programs` | JSON array of all programs (id, name, emoji, created_at) |
| `{program_id}:profile` | Learner's native language, goals, preferred learning style |
| `{program_id}:assessment` | Current proficiency level (A1-C2), strengths, areas to improve |
| `{program_id}:vocabulary` | Spaced repetition data per word (next_review, interval, streak) |
| `{program_id}:grammar` | Grammar concepts covered and mastery level |
| `{program_id}:weak_points` | Error patterns (spelling, grammar, conjugation, etc.) |
| `{program_id}:session_history` | Summary of recent sessions and topics covered |
| `{program_id}:last_session` | Summary of the most recent session |
| `{program_id}:stats` | Total sessions, words learned, quizzes taken, accuracy rates |

### Agent Integration

The language tutor system prompt (`LANGUAGE_TUTOR_SYSTEM_PROMPT` in `prompts.py`) includes:
- KV storage rules and key documentation
- Quiz format specifications (multiple-choice, fill-blank, translate, batch)
- Spaced repetition system, CEFR level guidance, error correction strategy
- First session (assessment) and returning session (new lesson) workflows
- L1-aware teaching and comprehensible input (i+1) guidelines

Context caching is disabled for language conversations to ensure fresh KV data is always included.

## Quiz Blocks

The AI generates interactive quizzes using ` ```quiz ` fenced code blocks with JSON content. **All evaluation is done by the LLM** — the client only collects answers and sends them back.

### Quiz Types

**Multiple Choice**
```json
{
  "type": "multiple-choice",
  "question": "What does 'Hola' mean?",
  "options": ["Goodbye", "Hello", "Thank you", "Please"],
  "correct": 1
}
```

**Fill in the Blank**
```json
{
  "type": "fill-blank",
  "question": "Complete: Je ___ français.",
  "answer": "parle",
  "hint": "First person singular of 'parler'"
}
```

**Translation**
```json
{
  "type": "translate",
  "question": "Translate to English: 'Wo ist der Bahnhof?'",
  "answer": "Where is the train station?"
}
```

**Batch** (multiple questions in one block)
```json
{
  "type": "batch",
  "title": "Vocabulary Review",
  "questions": [...]
}
```

### Evaluation Flow

1. The `marked` renderer intercepts `lang === 'quiz'` code blocks
2. `renderQuizBlock()` in `QuizBlock.ts` parses the JSON and returns HTML
3. Event delegation on `#messages` handles `.quiz-option`, `.quiz-submit`, and `.quiz-continue` clicks
4. User clicks/submits answers — UI locks them in with neutral "submitted" styling (no correct/incorrect)
5. After all questions are answered, a "Continue" button appears
6. Clicking "Continue" sends all answers to the LLM in a structured format:
   ```
   My quiz answers:

   1. What does 'Hola' mean? → Hello
   2. Complete: Je ___ français. → parle
   ```
7. The LLM evaluates answers with linguistic nuance and provides feedback
8. Quizzes in older messages are automatically locked (non-interactive)

### Why LLM Evaluation

Client-side string matching can't handle:
- Alternative phrasings ("Where is the station?" vs "Where's the station?")
- Minor spelling variations that are still acceptable
- Equivalent translations with different word order
- Partial credit or "close enough" answers

The LLM evaluates all quiz types (including multiple-choice) for a single, consistent code path.

## Frontend

### Program Creation

Programs are created via a dropdown that shows flag emoji + language name from a predefined list. Languages that already have programs are filtered out to prevent duplicates.

### Key Files

| File | Purpose |
|------|---------|
| `web/src/core/language.ts` | Navigation, CRUD, auto-trigger first message |
| `web/src/components/LanguageDashboard.ts` | Programs list, language dropdown modal, chat header |
| `web/src/components/QuizBlock.ts` | Quiz rendering and answer collection |
| `web/src/styles/components/language.css` | Language UI styles |
| `web/src/styles/components/quiz.css` | Quiz block styles |

### Routing

- `#/language` - Programs list view
- `#/language/{programId}` - Program chat view

### State

Zustand store fields:
- `isLanguageView` - Whether language view is active
- `languagePrograms` - Cached programs list
- `languageCurrentProgram` - Current program ID (when in chat view)
- `languageProgramsLastFetch` - Timestamp for cache invalidation

### Session Lifecycle

- **New program**: Auto-sends "Let's start!" → LLM sees no KV data → runs assessment
- **Returning (open existing)**: Conversation has message history → LLM continues from context
- **New Lesson (reset)**: Messages cleared, KV data persists → auto-sends "Let's start!" → LLM sees KV data → starts a new lesson (not reassessment)

## Testing

- **Unit tests**: `tests/unit/test_language_db.py` - Database mixin operations
- **Integration tests**: `tests/integration/test_routes_language.py` - API endpoint tests
- **Visual tests**: `web/tests/visual/language.visual.ts` - UI screenshot tests
- **Quiz tests**: `web/tests/unit/quiz-block.test.ts` - Quiz rendering and answer collection
