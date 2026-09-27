"""Chunk, ingest and retrieve synthetic documents with mandatory Qdrant access filters."""

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import date
from uuid import NAMESPACE_URL, uuid4, uuid5

import httpx

from assistops.config import Settings
from assistops.corpus import Document


@dataclass(frozen=True)
class Chunk:
    id: str
    text: str
    payload: dict


def chunk_documents(documents: list[Document], size: int = 180, overlap: int = 30) -> list[Chunk]:
    if not 0 <= overlap < size:
        raise ValueError("Overlap must be smaller than the chunk size")
    chunks = []
    for document in documents:
        metadata = document.metadata
        sections = re.split(r"(?m)^## ", document.body)
        for section_index, section in enumerate(sections):
            # The preamble contains only the title and synthetic disclosure in this corpus.
            if section_index == 0:
                continue
            heading, _, text = section.partition("\n")
            words = text.split()
            for start in range(0, len(words), size - overlap):
                content = " ".join(words[start : start + size])
                if not content:
                    continue
                embedding_text = f"{metadata.title}\n{heading}\n{content}"
                identifier = str(
                    uuid5(
                        NAMESPACE_URL,
                        f"{metadata.tenant_id}/{metadata.key}/{section_index}/{start}/{embedding_text}",
                    )
                )
                payload = {
                    "document_key": metadata.key,
                    "tenant_id": metadata.tenant_id,
                    "allowed_roles": metadata.allowed_roles,
                    "status": metadata.status,
                    "valid_from": metadata.effective_from.toordinal(),
                    "valid_until": (metadata.effective_until or date.max).toordinal(),
                    "title": metadata.title,
                    "section": heading,
                    "text": content,
                    "source_path": document.relative_path,
                    "origin": metadata.origin,
                }
                chunks.append(Chunk(identifier, embedding_text, payload))
                if start + size >= len(words):
                    break
    if not chunks:
        raise ValueError("No document sections to index")
    return chunks


def access_filter(tenant: str, roles: set[str], as_of: date) -> dict:
    if not tenant or not roles:
        raise ValueError("Trusted tenant and roles are required")
    return {
        "must": [
            {"key": "tenant_id", "match": {"value": tenant}},
            {"key": "allowed_roles", "match": {"any": sorted(roles)}},
            {"key": "status", "match": {"value": "active"}},
            {"key": "valid_from", "range": {"lte": as_of.toordinal()}},
            {"key": "valid_until", "range": {"gt": as_of.toordinal()}},
        ]
    }


class Retriever:
    def __init__(self, settings: Settings, embedder, alias: str = "assistops_knowledge"):
        if not re.fullmatch(r"[a-zA-Z0-9_-]{1,80}", alias):
            raise ValueError("Invalid collection alias")
        self.alias = alias
        self.embedder = embedder
        headers = (
            {"api-key": settings.qdrant_api_key.get_secret_value()}
            if settings.qdrant_api_key
            else {}
        )
        self.client = httpx.Client(
            base_url=settings.qdrant_url.rstrip("/"), headers=headers, timeout=30
        )

    def close(self):
        self.client.close()

    def request(self, method, path, **kwargs):
        response = self.client.request(method, path, **kwargs)
        if not response.is_success:
            raise RuntimeError(f"Qdrant request failed (HTTP {response.status_code})")
        return response.json()["result"]

    def pin_snapshot(self) -> str:
        """Keep all queries in an evaluation on the same immutable collection."""
        aliases = self.request("GET", "/aliases")["aliases"]
        self.alias = next(
            item["collection_name"] for item in aliases if item["alias_name"] == self.alias
        )
        return self.alias

    def ingest(self, documents: list[Document]) -> dict:
        chunks = chunk_documents(documents)
        fingerprint = hashlib.sha256(
            json.dumps(
                [{"text": chunk.text, "payload": chunk.payload} for chunk in chunks],
                sort_keys=True,
                ensure_ascii=False,
            ).encode()
        ).hexdigest()
        self.request("GET", "/collections")
        vectors = self.embedder.embed([chunk.text for chunk in chunks])
        collection = f"{self.alias}_{fingerprint[:12]}_{uuid4().hex[:8]}"
        # A fresh snapshot avoids stale chunks after document removal or permission changes.
        self.request(
            "PUT",
            f"/collections/{collection}",
            json={
                "vectors": {
                    self.embedder.vector_name: {
                        "size": self.embedder.dimensions,
                        "distance": "Cosine",
                    }
                }
            },
        )
        for offset in range(0, len(chunks), 32):
            self.request(
                "PUT",
                f"/collections/{collection}/points?wait=true",
                json={
                    "points": [
                        {
                            "id": chunk.id,
                            "vector": {self.embedder.vector_name: vector},
                            "payload": chunk.payload,
                        }
                        for chunk, vector in zip(
                            chunks[offset : offset + 32], vectors[offset : offset + 32], strict=True
                        )
                    ]
                },
            )
        aliases = self.request("GET", "/aliases")["aliases"]
        actions = []
        if any(item["alias_name"] == self.alias for item in aliases):
            actions.append({"delete_alias": {"alias_name": self.alias}})
        actions.append({"create_alias": {"collection_name": collection, "alias_name": self.alias}})
        # Readers see the old or the complete new snapshot, never a partially uploaded index.
        self.request("POST", "/collections/aliases", json={"actions": actions})
        return {
            "collection": collection,
            "alias": self.alias,
            "chunks": len(chunks),
            "documents": len(documents),
            "corpus_sha256": fingerprint,
            "model": self.embedder.vector_name,
            "tokens_used": self.embedder.tokens_used,
        }

    def search(
        self, query: str, tenant: str, roles: set[str], as_of: date, limit: int = 5
    ) -> list[dict]:
        if not query.strip() or len(query) > 4000 or not 1 <= limit <= 20:
            raise ValueError("Invalid query or result limit")
        filters = access_filter(tenant, roles, as_of)
        vector = self.embedder.embed([query])[0]
        # Grouping ranks distinct documents by their best chunk, rather than truncating duplicates.
        result = self.request(
            "POST",
            f"/collections/{self.alias}/points/query/groups",
            json={
                "query": vector,
                "using": self.embedder.vector_name,
                "filter": filters,
                "group_by": "document_key",
                "group_size": 2,
                "limit": limit,
                "with_payload": True,
                "params": {"exact": True},
            },
        )
        sources = []
        for group in result["groups"]:
            if not group["hits"]:
                raise RuntimeError("Qdrant returned an empty group")
            passages = []
            for hit in group["hits"]:
                payload = hit["payload"]
                # Defense in depth: reject unexpected server results before returning source text.
                if not (
                    payload["tenant_id"] == tenant
                    and payload["document_key"] == group["id"]
                    and set(payload["allowed_roles"]) & roles
                    and payload["status"] == "active"
                    and payload["valid_from"] <= as_of.toordinal() < payload["valid_until"]
                ):
                    raise RuntimeError("Qdrant returned an ineligible source")
                passages.append(
                    {
                        "chunk_id": hit["id"],
                        "section": payload["section"],
                        "text": payload["text"],
                        "score": hit["score"],
                    }
                )
            sources.append(
                {
                    "document": group["id"],
                    "title": payload["title"],
                    "source_path": payload["source_path"],
                    "origin": payload["origin"],
                    "passages": passages,
                }
            )
        return sources
