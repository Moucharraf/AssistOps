"""Bounded OpenAI embedding requests with a local, content-addressed vector cache."""

import hashlib
import json
import math
import time
from pathlib import Path
from uuid import uuid4

import httpx

from assistops.config import Settings


class OpenAIEmbeddings:
    def __init__(self, settings: Settings, cache: Path = Path(".cache/embeddings")):
        if not settings.openai_api_key:
            raise ValueError("Configure OPENAI_API_KEY or ASSISTOPS_OPENAI_API_KEY")
        self.model = settings.embedding_model
        self.dimensions = settings.embedding_dimensions
        self.vector_name = f"openai_{self.model}_{self.dimensions}"
        self.cache = cache
        self.cache.mkdir(parents=True, exist_ok=True)
        self.tokens_used = 0
        self.requested_bytes = 0
        self.max_requested_bytes = 100_000
        self.client = httpx.Client(
            base_url="https://api.openai.com/v1",
            timeout=30,
            headers={"Authorization": f"Bearer {settings.openai_api_key.get_secret_value()}"},
        )

    def close(self):
        self.client.close()

    def valid_vector(self, vector):
        return (
            isinstance(vector, list)
            and len(vector) == self.dimensions
            and all(type(value) in (int, float) and math.isfinite(value) for value in vector)
        )

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts or any(not text.strip() or len(text) > 16000 for text in texts):
            raise ValueError("Embedding input must contain nonempty, bounded text")
        paths = [
            self.cache
            / (hashlib.sha256(f"{self.vector_name}\n{text}".encode()).hexdigest() + ".json")
            for text in texts
        ]
        vectors = []
        for path in paths:
            try:
                vector = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                vector = None
            vectors.append(vector if self.valid_vector(vector) else None)
        missing = [index for index, vector in enumerate(vectors) if vector is None]
        for offset in range(0, len(missing), 32):
            batch = missing[offset : offset + 32]
            response = None
            for attempt in range(3):
                # Count retries conservatively: a lost response may still have been billed.
                size = sum(len(texts[index].encode("utf-8")) for index in batch)
                if self.requested_bytes + size > self.max_requested_bytes:
                    raise RuntimeError("Embedding request budget exhausted (100000 UTF-8 bytes)")
                self.requested_bytes += size
                try:
                    response = self.client.post(
                        "/embeddings",
                        json={
                            "model": self.model,
                            "dimensions": self.dimensions,
                            "input": [texts[index] for index in batch],
                            "encoding_format": "float",
                        },
                    )
                except httpx.TransportError:
                    if attempt == 2:
                        raise RuntimeError("Embedding service unreachable") from None
                else:
                    if response.status_code == 200:
                        break
                    if response.status_code != 429 and response.status_code < 500:
                        # Provider response bodies may contain input text; never expose them.
                        raise RuntimeError(
                            f"Embedding request rejected (HTTP {response.status_code})"
                        )
                time.sleep(0.5 * 2**attempt)
            else:
                raise RuntimeError("Embedding retries exhausted")
            data = response.json()
            ordered = sorted(data["data"], key=lambda item: item["index"])
            if [item["index"] for item in ordered] != list(range(len(batch))):
                raise RuntimeError("Embedding response indices do not match the request")
            if not all(self.valid_vector(item["embedding"]) for item in ordered):
                raise RuntimeError("Embedding response has invalid vectors")
            self.tokens_used += data.get("usage", {}).get("total_tokens", 0)
            for index, item in zip(batch, ordered, strict=True):
                vectors[index] = item["embedding"]
                # Atomic replacement prevents interrupted writes from poisoning the cache.
                temporary = paths[index].with_suffix(f".{uuid4().hex}.tmp")
                temporary.write_text(json.dumps(vectors[index]), encoding="utf-8")
                temporary.replace(paths[index])
        return vectors
