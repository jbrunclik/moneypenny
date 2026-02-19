# AI Chatbot Documentation

This directory contains detailed documentation for the AI Chatbot project, organized by feature area and concern.

## Documentation Structure

### Features (`features/`)
Feature-specific documentation covering user-facing functionality:

- **[agents.md](features/agents.md)** - Autonomous agents with cron scheduling, approval workflow, Command Center UI, agent-to-agent communication
- **[chat-and-streaming.md](features/chat-and-streaming.md)** - Gemini API integration, streaming responses, thinking indicators, web search sources, tool forcing
- **[file-handling.md](features/file-handling.md)** - Image generation (including image-to-image editing), code execution sandbox, file uploads, clipboard paste, upload progress, background thumbnail generation
- **[voice-and-tts.md](features/voice-and-tts.md)** - Voice input (speech-to-text), text-to-speech
- **[search.md](features/search.md)** - Full-text search with SQLite FTS5, O(1) message navigation
- **[sync.md](features/sync.md)** - Real-time synchronization across devices/tabs with timestamp-based polling
- **[integrations.md](features/integrations.md)** - Todoist and Google Calendar OAuth integrations with full API coverage
- **[memory-and-context.md](features/memory-and-context.md)** - User memory, custom instructions, user context, anonymous mode, memory defragmentation
- **[cost-tracking.md](features/cost-tracking.md)** - Token usage tracking, image generation costs, currency rates, monthly aggregation
- **[ui-features.md](features/ui-features.md)** - Input toolbar, conversation management, deep linking, version banner, color scheme, clipboard operations

### Architecture (`architecture/`)
System design and architectural decisions:

- **[authentication.md](architecture/authentication.md)** - Google Sign-In, JWT token handling, token refresh, @require_auth decorator
- **[database.md](architecture/database.md)** - Blob storage, connection pooling, indexes, performance monitoring, vacuum, backup, best practices
- **[api-design.md](architecture/api-design.md)** - OpenAPI documentation, rate limiting, request validation (including magic bytes), comprehensive error handling
- **[streaming-metadata.md](architecture/streaming-metadata.md)** - Streaming metadata handling, MSG_CONTEXT/METADATA markers, malformed metadata bug fix, debugging guide

### UI (`ui/`)
User interface patterns and implementations:

- **[scroll-behavior.md](ui/scroll-behavior.md)** - Complex scroll scenarios, programmatic scroll wrapper, streaming auto-scroll, race condition fixes, cursor-based pagination
- **[mobile-and-pwa.md](ui/mobile-and-pwa.md)** - iOS Safari gotchas (9 documented issues), touch gestures, PWA viewport fixes
- **[components.md](ui/components.md)** - CSS architecture, design system variables, component patterns, popup escape handler

### General

- **[testing.md](testing.md)** - Test structure (backend and frontend), patterns, E2E server with parallel execution, visual regression tests
- **[logging.md](logging.md)** - Structured logging (backend JSON format, frontend logger utility), request IDs, logging guidelines
- **[conventions.md](conventions.md)** - Code quality guidelines, refactoring patterns, file size rules

## Quick Links

### Most Referenced

- [Agents](features/agents.md) - Autonomous agents and Command Center
- [Chat and Streaming](features/chat-and-streaming.md) - Core chat functionality
- [File Handling](features/file-handling.md) - Working with files and images
- [Database](architecture/database.md) - Database architecture and best practices
- [API Design](architecture/api-design.md) - API patterns and validation
- [Testing](testing.md) - How to write and run tests

### For New Developers

Start here to understand the system:
1. Read the main [../CLAUDE.md](../CLAUDE.md) for quick reference and development workflow
2. Explore [Architecture](architecture/) docs to understand system design
3. Review [Features](features/) docs for specific functionality
4. Check [Testing](testing.md) before making changes

### For Feature Development

When working on a specific area:
1. Read the relevant feature doc first
2. Check related architecture docs for design patterns
3. Review testing patterns and add tests
4. Follow code style guidelines in ../CLAUDE.md

### For Debugging

Common debugging scenarios:
- **Scroll issues**: See [Scroll Behavior](ui/scroll-behavior.md) - 25+ documented scenarios
- **Mobile/PWA issues**: See [Mobile and PWA](ui/mobile-and-pwa.md) - iOS Safari gotchas
- **Authentication errors**: See [Authentication](architecture/authentication.md) - Error codes and handling
- **Database performance**: See [Database](architecture/database.md) - Slow query logging, indexes
- **API errors**: See [API Design](architecture/api-design.md) - Error handling patterns
- **Empty messages after reload**: See [Streaming Metadata](architecture/streaming-metadata.md) - Malformed METADATA bug

## Documentation Guidelines

### When to Update Documentation

**Update CLAUDE.md when:**
- Adding new common tasks (e.g., new Make targets)
- Changing development workflow
- Updating quick reference commands
- Adding code style guidelines that apply project-wide

**Update feature docs when:**
- Implementing new features
- Changing how existing features work
- Adding configuration options
- Modifying API endpoints
- Changing UI behavior

**Update architecture docs when:**
- Changing authentication/authorization
- Modifying database schema
- Adding new validation rules
- Changing error handling patterns
- Updating rate limits

**Update UI docs when:**
- Changing scroll behavior
- Adding new mobile/PWA features
- Modifying CSS architecture
- Adding new component patterns

### How to Update Documentation

1. **Find the right doc** - Check this index
2. **Update inline** - Documentation is next to code for easy maintenance
3. **Update "See Also" sections** - Keep cross-references current
4. **Test examples** - Verify code examples still work
5. **Keep CLAUDE.md lean** - Detailed info goes in `docs/`, not here

### Adding New Features - Documentation Checklist

When implementing a significant new feature:

1. ✅ Add feature documentation to appropriate `docs/features/` file
2. ✅ Update architecture docs if system design changes
3. ✅ Add testing section to feature doc
4. ✅ Update `docs/README.md` index if adding new doc
5. ✅ Add pointer to detailed doc from CLAUDE.md (if it's a common task)
6. ✅ Update `.env.example` if adding environment variables
7. ✅ Update README.md if feature is user-facing

### Style Guide

- Use clear headings with `#`, `##`, `###` hierarchy
- Include code examples with syntax highlighting (` ```python ` or ` ```typescript `)
- Link to source files with relative paths (`../../src/...`)
- Use tables for structured data (e.g., configuration options, API endpoints)
- Add "See Also" sections at the end linking to related docs
- Keep line length reasonable (~120 chars max) for readability

### Quick Rules

1. **Keep it DRY**: Don't duplicate content between files. Use links to reference related information.
2. **Use relative links**: Link to other docs using relative paths (e.g., `[Database](architecture/database.md)`)
3. **Add "See Also" sections**: Help readers find related content
4. **Include code examples**: Show don't tell - provide concrete examples
5. **Update CLAUDE.md**: Add pointer to detailed doc if it's a common task

## Refactoring Completed

The documentation has been successfully refactored from a monolithic 3,921-line CLAUDE.md into:

- **1 streamlined reference** (CLAUDE.md - 390 lines) with quick reference and pointers
  - **Note**: `CLAUDE.md` is a symlink to `AGENTS.md` (the canonical file)
  - Both names point to the same content for compatibility
- **19 focused documentation files** (~60KB total) covering all topics in depth
- **Organized structure** with clear categorization (features, architecture, UI, general)
- **Comprehensive coverage** with 25+ scroll scenarios, 9 iOS gotchas, full API patterns, etc.

### Benefits

✅ **Faster**: Smaller system prompt means faster and cheaper AI interactions
✅ **Discoverable**: Clear organization makes information easy to find
✅ **Maintainable**: Focused files are easier to update than one giant file
✅ **Comprehensive**: More detailed coverage with room to expand
✅ **Accessible**: Claude can read specific docs when needed without loading everything

## Contributing

When adding new features:
1. Update or create the appropriate documentation file in the relevant directory
2. Add a link to it in this README
3. Add a pointer from [../CLAUDE.md](../CLAUDE.md) if it's a common task
4. Ensure all internal links work correctly
5. Follow the documentation style guide in CLAUDE.md
