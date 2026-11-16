"""Text embeddings for semantic recall (memories, past conversations).

Vectors come from the Gemini embedding API and are stored as packed float32
blobs in the embeddings table. Similarity search is brute-force cosine in
Python - at family scale (a few thousand vectors per user) that beats the
complexity of a vector-index extension.

Every entry point degrades gracefully: embed_text returns None on any
failure, and callers fall back to keyword-only search.
"""

import math
import struct
from array import array
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


def top_k_similar(
    query_vec: list[float],
    candidates: list[tuple[str, bytes]],
    k: int,
) -> list[tuple[str, float]]:
    """Rank (ref_id, packed_vector) candidates by cosine similarity, best first.

    Vectors are stored little-endian float32 and read natively (every host
    this runs on is little-endian). ``math.sumprod`` over ``array("f")`` runs in C: ~3x faster than the
    per-element loop for a user's ~11k message vectors (Nov 16 2026). A zero
    vector or one of another dimension scores 0.0.
    """
    query_norm = math.sqrt(math.sumprod(query_vec, query_vec))
    scored: list[tuple[str, float]] = []
    for ref_id, blob in candidates:
        vector = array("f")
        vector.frombytes(blob[: len(blob) // 4 * 4])
        if len(vector) != len(query_vec) or query_norm == 0.0:
            scored.append((ref_id, 0.0))
            continue
        norm = math.sqrt(math.sumprod(vector, vector))
        score = math.sumprod(query_vec, vector) / (query_norm * norm) if norm else 0.0
        scored.append((ref_id, score))
    scored.sort(key=lambda pair: pair[1], reverse=True)
    return scored[:k]
