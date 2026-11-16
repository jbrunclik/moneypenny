"""Tests for the embedding utility (pack/cosine/async store)."""

import math
import struct
from unittest.mock import MagicMock, patch

from src.config import Config
from src.utils.embeddings import embed_text, pack_vector, top_k_similar


def unpack_vector(blob: bytes) -> list[float]:
    return list(struct.unpack(f"<{len(blob) // 4}f", blob))


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """The reference: top_k_similar's score for one candidate."""
    [(_, score)] = top_k_similar(a, [("x", pack_vector(b))], 1)
    return score


def _reference_cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norms = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return dot / norms if norms else 0.0


class TestPacking:
    def test_roundtrip(self) -> None:
        vec = [0.1, -0.5, 3.25, 0.0]
        unpacked = unpack_vector(pack_vector(vec))
        assert len(unpacked) == 4
        for a, b in zip(vec, unpacked, strict=True):
            assert math.isclose(a, b, rel_tol=1e-6)


class TestCosine:
    def test_identical_vectors(self) -> None:
        assert math.isclose(cosine_similarity([1.0, 2.0], [1.0, 2.0]), 1.0, rel_tol=1e-9)

    def test_orthogonal_vectors(self) -> None:
        assert math.isclose(cosine_similarity([1.0, 0.0], [0.0, 1.0]), 0.0, abs_tol=1e-9)

    def test_zero_vector_is_zero_similarity(self) -> None:
        assert cosine_similarity([0.0, 0.0], [1.0, 1.0]) == 0.0


class TestTopKSimilar:
    def test_orders_by_similarity(self) -> None:
        query = [1.0, 0.0]
        candidates = [
            ("far", pack_vector([0.0, 1.0])),
            ("near", pack_vector([1.0, 0.1])),
            ("mid", pack_vector([1.0, 1.0])),
        ]

        ranked = top_k_similar(query, candidates, k=2)

        assert [ref_id for ref_id, _score in ranked] == ["near", "mid"]
        assert ranked[0][1] > ranked[1][1]


class TestEmbedText:
    @patch("src.utils.embeddings._get_client")
    def test_returns_vector_values(self, mock_get_client: MagicMock) -> None:
        embedding = MagicMock()
        embedding.values = [0.1, 0.2]
        response = MagicMock()
        response.embeddings = [embedding]
        client = MagicMock()
        client.models.embed_content.return_value = response
        mock_get_client.return_value = client

        assert embed_text("hello") == [0.1, 0.2]

    @patch("src.utils.embeddings._get_client")
    def test_returns_none_on_failure(self, mock_get_client: MagicMock) -> None:
        client = MagicMock()
        client.models.embed_content.side_effect = RuntimeError("api down")
        mock_get_client.return_value = client

        assert embed_text("hello") is None

    def test_empty_text_returns_none(self) -> None:
        assert embed_text("   ") is None


class TestEmbeddingClient:
    def test_client_has_a_request_deadline(self) -> None:
        """Oct 2026 prod: one embed call hung ~165 s (the SDK default is no
        timeout) and stalled a whole chat turn inside search_conversations."""
        from src.utils import embeddings

        with patch("google.genai.Client") as client_cls:
            embeddings._new_client()

        http_options = client_cls.call_args.kwargs["http_options"]
        assert http_options.timeout == Config.EMBEDDING_TIMEOUT_SECONDS * 1000


# --- Nov 16 2026: sumprod scoring matches the old cosine loop --------------


def test_top_k_matches_the_reference_cosine() -> None:
    import random

    rng = random.Random(7)
    query = [rng.uniform(-1, 1) for _ in range(16)]
    candidates = [
        (f"r{i}", pack_vector([rng.uniform(-1, 1) for _ in range(16)])) for i in range(50)
    ]
    expected = sorted(
        ((ref, _reference_cosine(query, unpack_vector(blob))) for ref, blob in candidates),
        key=lambda pair: pair[1],
        reverse=True,
    )[:10]
    got = top_k_similar(query, candidates, 10)
    assert [ref for ref, _ in got] == [ref for ref, _ in expected]
    for (_, a), (_, b) in zip(got, expected, strict=True):
        assert abs(a - b) < 1e-5


def test_top_k_zero_and_mismatched_vectors_score_zero() -> None:
    got = dict(
        top_k_similar(
            [1.0, 0.0], [("zero", pack_vector([0.0, 0.0])), ("short", pack_vector([1.0]))], 5
        )
    )
    assert got == {"zero": 0.0, "short": 0.0}
