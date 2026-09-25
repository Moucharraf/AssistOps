import hashlib
import json
import os
from datetime import date
from pathlib import Path
from uuid import uuid4

import httpx
import pytest

from assistops.config import Settings
from assistops.corpus import load_corpus
from assistops.embeddings import OpenAIEmbeddings
from assistops.retrieval import Retriever, access_filter, chunk_documents

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def embedder(tmp_path):
    settings = Settings(_env_file=None, OPENAI_API_KEY="test-key", embedding_dimensions=256)
    instance = OpenAIEmbeddings(settings, tmp_path / "cache")
    instance.client.close()
    yield instance
    instance.close()


def test_embedding_cache_avoids_repeat_billing(embedder):
    calls = []

    def handler(request):
        calls.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={"data": [{"index": 0, "embedding": [1.0] * 256}], "usage": {"total_tokens": 4}},
        )

    embedder.client = httpx.Client(
        base_url="https://api.openai.com/v1", transport=httpx.MockTransport(handler)
    )
    first = embedder.embed(["document synthétique"])
    assert embedder.embed(["document synthétique"]) == first
    assert len(calls) == 1
    assert embedder.tokens_used == 4


def test_budget_blocks_call_before_sending(embedder):
    embedder.max_requested_bytes = 1
    embedder.client = httpx.Client(
        transport=httpx.MockTransport(
            lambda _: pytest.fail("Budget violation must not send a request")
        )
    )
    with pytest.raises(RuntimeError, match="budget exhausted"):
        embedder.embed(["test"])


def test_provider_error_body_is_not_exposed(embedder):
    embedder.client = httpx.Client(
        base_url="https://api.openai.com/v1",
        transport=httpx.MockTransport(
            lambda _: httpx.Response(401, json={"secret": "private-value"})
        ),
    )
    with pytest.raises(RuntimeError) as error:
        embedder.embed(["test"])
    assert "private-value" not in str(error.value)


def test_chunks_are_stable_bounded_and_keep_permissions():
    docs = load_corpus(ROOT / "data/knowledge")
    chunks = chunk_documents(docs)
    assert chunks == chunk_documents(docs)
    assert len(chunks) == len({chunk.id for chunk in chunks})
    assert all(len(chunk.payload["text"].split()) <= 180 for chunk in chunks)
    assert all(chunk.payload["origin"] == "synthetic" for chunk in chunks)
    restricted = [c for c in chunks if c.payload["document_key"] == "refund-approvals@1"]
    assert restricted
    assert all("customer" not in c.payload["allowed_roles"] for c in restricted)


def test_empty_roles_fail_closed():
    with pytest.raises(ValueError):
        access_filter("demo", set(), date(2026, 9, 1))


class TestVectors:
    """Deterministic test double, not a semantic model or a retrieval quality baseline."""

    __test__ = False
    vector_name = "test_vectors_16"
    dimensions = 16
    tokens_used = 0

    def embed(self, texts):
        return [
            [float(value + 1) for value in hashlib.md5(text.encode()).digest()] for text in texts
        ]


def test_failed_upload_does_not_publish_alias(settings):
    retriever = Retriever(settings, TestVectors(), "isolated_test")
    retriever.client.close()
    paths = []

    def handler(request):
        paths.append(request.url.path)
        if "/points" in request.url.path:
            return httpx.Response(500)
        return httpx.Response(200, json={"result": {}})

    retriever.client = httpx.Client(
        base_url="http://qdrant", transport=httpx.MockTransport(handler)
    )
    try:
        with pytest.raises(RuntimeError):
            retriever.ingest(load_corpus(ROOT / "data/knowledge"))
        assert "/collections/aliases" not in paths
    finally:
        retriever.close()


@pytest.mark.integration
def test_real_qdrant_filters_and_snapshot_replacement():
    url = os.environ.get("ASSISTOPS_TEST_QDRANT_URL")
    if not url:
        pytest.skip("Set ASSISTOPS_TEST_QDRANT_URL for real Qdrant tests")
    alias = "test_rag_" + uuid4().hex
    retriever = Retriever(Settings(_env_file=None, qdrant_url=url), TestVectors(), alias)
    collections = []
    docs = load_corpus(ROOT / "data/knowledge")
    try:
        first = retriever.ingest(docs)
        collections.append(first["collection"])
        sources = retriever.search("remboursement", "demo", {"customer"}, date(2026, 9, 1), 20)
        expected = {
            d.metadata.key for d in docs if d.visible_to("demo", {"customer"}, date(2026, 9, 1))
        }
        assert {source["document"] for source in sources} == expected
        assert retriever.search("test", "unknown", {"customer"}, date(2026, 9, 1)) == []
        second = retriever.ingest([d for d in docs if d.metadata.key == "plans@1"])
        collections.append(second["collection"])
        assert [
            s["document"] for s in retriever.search("test", "demo", {"customer"}, date(2026, 9, 1))
        ] == ["plans@1"]
    finally:
        # Delete only the UUID-namespaced resources created by this test.
        if collections:
            retriever.request(
                "POST",
                "/collections/aliases",
                json={"actions": [{"delete_alias": {"alias_name": alias}}]},
            )
        for collection in collections:
            retriever.request("DELETE", f"/collections/{collection}")
        retriever.close()
