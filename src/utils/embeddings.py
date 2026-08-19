"""Text embeddings for semantic recall (memories, past conversations).

Vectors come from the Gemini embedding API and are stored as packed float32
blobs in the embeddings table. Similarity search is brute-force cosine in
Python - at family scale (a few thousand vectors per user) that beats the
complexity of a vector-index extension.

Every entry point degrades gracefully: embed_text returns None on any
failure, and callers fall back to keyword-only search.
"""

import struct
import threading
from typing import Any

from src.config import Config
from src.utils.logging import get_logger

logger = get_logger(__name__)

_MAX_EMBED_CHARS = 8000

_client: Any | None = None
_client_lock = threading.Lock()


def _get_client() -> Any:
    """Lazy, process-wide google.genai client (same pattern as context_cache)."""
    global _client
    if _client is None:
        with _client_lock:
            if _client is None:
                from google import genai

                _client = genai.Client(api_key=Config.GEMINI_API_KEY)
    return _client


def embed_text(text: str) -> list[float] | None:
    """Embed one text; None on any failure (callers degrade to keyword search)."""
    text = (text or "").strip()
    if not text:
        return None
    try:
        response = _get_client().models.embed_content(
            model=Config.EMBEDDING_MODEL,
            contents=text[:_MAX_EMBED_CHARS],
            config={"output_dimensionality": Config.EMBEDDING_DIM},
        )
        values: list[float] = list(response.embeddings[0].values)
        return values
    except Exception as e:
        logger.warning("Embedding failed", extra={"error": str(e), "text_length": len(text)})
        return None


def pack_vector(vec: list[float]) -> bytes:
    """Pack a vector as little-endian float32 bytes for BLOB storage."""
    return struct.pack(f"<{len(vec)}f", *vec)


def unpack_vector(blob: bytes) -> list[float]:
    """Unpack a float32 BLOB back into a list of floats."""
    count = len(blob) // 4
    return list(struct.unpack(f"<{count}f", blob[: count * 4]))


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Cosine similarity; 0.0 for zero-length or zero vectors."""
    if len(a) != len(b) or not a:
        return 0.0
    dot: float = sum(x * y for x, y in zip(a, b, strict=True))
    norm_a: float = sum(x * x for x in a) ** 0.5
    norm_b: float = sum(y * y for y in b) ** 0.5
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


def top_k_similar(
    query_vec: list[float],
    candidates: list[tuple[str, bytes]],
    k: int,
) -> list[tuple[str, float]]:
    """Rank (ref_id, packed_vector) candidates by cosine similarity, best first."""
    scored = [
        (ref_id, cosine_similarity(query_vec, unpack_vector(blob))) for ref_id, blob in candidates
    ]
    scored.sort(key=lambda pair: pair[1], reverse=True)
    return scored[:k]


def embed_and_store_async(user_id: str, kind: str, ref_id: str, text: str) -> None:
    """Embed text and upsert it into the embeddings table on a daemon thread.

    Fire-and-forget: failures are logged, never raised - embedding freshness
    is best-effort and the write path must not block on the embedding API.
    """
    if not Config.EMBEDDINGS_ENABLED:
        return

    def _work() -> None:
        from src.db.models import db

        vec = embed_text(text)
        if vec is None:
            return
        try:
            db.upsert_embedding(
                user_id, kind, ref_id, Config.EMBEDDING_MODEL, len(vec), pack_vector(vec)
            )
        except Exception:
            logger.warning(
                "Failed to store embedding",
                extra={"kind": kind, "ref_id": ref_id},
                exc_info=True,
            )

    threading.Thread(target=_work, daemon=True, name=f"embed-{kind}").start()
