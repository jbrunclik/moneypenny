"""Tests for the embedding utility (pack/cosine/async store)."""

import math
from unittest.mock import MagicMock, patch

from src.utils.embeddings import (
    cosine_similarity,
    embed_text,
    pack_vector,
    top_k_similar,
    unpack_vector,
)


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
