"""
Initial database schema.

This migration creates the base tables for the chatbot application.
For existing databases, these tables already exist, so this is a no-op.
"""

from yoyo import step

steps = [
    step(
        # Up migration - create tables if they don't exist
        """
        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY,
            email TEXT UNIQUE NOT NULL,
            name TEXT,
            picture TEXT,
            created_at TEXT NOT NULL
        )
        """,
        # Down migration - drop table
        "DROP TABLE IF EXISTS users"
    ),
    step(
        """
        CREATE TABLE IF NOT EXISTS conversations (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            title TEXT NOT NULL,
            model TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
        """,
        "DROP TABLE IF EXISTS conversations"
    ),
    step(
        """
        CREATE TABLE IF NOT EXISTS messages (
            id TEXT PRIMARY KEY,
            conversation_id TEXT NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY (conversation_id) REFERENCES conversations(id)
        )
        """,
        "DROP TABLE IF EXISTS messages"
    ),
    step(
        """
        CREATE TABLE IF NOT EXISTS agent_states (
            conversation_id TEXT PRIMARY KEY,
            state_json TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY (conversation_id) REFERENCES conversations(id)
        )
        """,
        "DROP TABLE IF EXISTS agent_states"
    ),
]
