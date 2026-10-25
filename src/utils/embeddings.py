"""Text embeddings for semantic recall (memories, past conversations).

Vectors come from the Gemini embedding API and are stored as packed float32
blobs in the embeddings table. Similarity search is brute-force cosine in
Python - at family scale (a few thousand vectors per user) that beats the
complexity of a vector-index extension.

Every entry point degrades gracefully: embed_text returns None on any
failure, and callers fall back to keyword-only search.
"""

import struct
from typing import Any

from google import genai
from google.genai import types

from src.config import Config
from src.utils.lazy import Lazy
from src.utils.logging import get_logger

logger = get_logger(__name__)

_MAX_EMBED_CHARS = 8000


def _new_client() -> Any:

    return genai.Client(
        api_key=Config.GEMINI_API_KEY,
        http_options=types.HttpOptions(timeout=Config.EMBEDDING_TIMEOUT_SECONDS * 1000),
    )


# per-worker: a stateless API client
_client = Lazy(_new_client)


def _get_client() -> Any:
    return _client.get()


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
    except Exception as e:  # optional; callers degrade to keyword search
        logger.warning(
            "Embedding failed", extra={"error": str(e), "text_length": len(text)}, exc_info=True
        )
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
