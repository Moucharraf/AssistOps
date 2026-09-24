"""Load an explicitly allowlisted synthetic corpus without contacting external services."""

import argparse
import json
import tomllib
from datetime import date
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Metadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_id: str = Field(pattern=r"^[a-z][a-z0-9-]+$")
    title: str
    version: int = Field(ge=1)
    tenant_id: str
    language: Literal["fr"]
    category: str
    owner: str
    status: Literal["active", "archived"]
    effective_from: date
    effective_until: date | None = None
    allowed_roles: list[str] = Field(min_length=1)
    origin: Literal["synthetic"]
    synthetic_reason: str = Field(min_length=20)
    external_sources: list[str] = Field(max_length=0)

    @model_validator(mode="after")
    def valid_period(self):
        if self.effective_until and self.effective_until <= self.effective_from:
            raise ValueError("Document validity must have a positive duration")
        if self.status == "archived" and self.effective_until is None:
            raise ValueError("Archived documents need an end date")
        return self

    @property
    def key(self) -> str:
        return f"{self.document_id}@{self.version}"


class Document(BaseModel):
    metadata: Metadata
    body: str
    relative_path: str

    def visible_to(self, tenant_id: str, roles: set[str], as_of: date) -> bool:
        metadata = self.metadata
        # Access and validity are metadata constraints, never instructions taken from the body.
        return (
            metadata.tenant_id == tenant_id
            and bool(roles.intersection(metadata.allowed_roles))
            and metadata.status == "active"
            and metadata.effective_from <= as_of
            and (metadata.effective_until is None or as_of < metadata.effective_until)
        )


class Manifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1]
    corpus_id: str
    origin: Literal["synthetic"]
    language: Literal["fr"]
    snapshot_date: date
    external_content_included: Literal[False]
    documents: list[str] = Field(min_length=1)


class Evidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document: str
    quote: str = Field(min_length=10)


class Question(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^Q[0-9]+$")
    question: str = Field(min_length=10)
    tenant_id: str
    roles: list[str] = Field(min_length=1)
    as_of: date
    expected_behavior: Literal["answer", "abstain", "deny"]
    relevant_documents: list[str]
    expected_answer: str = Field(min_length=20)
    evidence: list[Evidence]
    forbidden_documents: list[str]


class Benchmark(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1]
    corpus_id: str
    origin: Literal["synthetic"]
    split: Literal["reference"]
    description: str
    questions: list[Question] = Field(min_length=1)


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def load_corpus(root: Path) -> list[Document]:
    root = root.resolve()
    manifest = Manifest.model_validate(read_json(root / "manifest.json"))
    documents = []
    seen_paths = set()
    seen_keys = set()
    # Only manifest entries can become retrieval inputs; evaluation files are never scanned.
    for relative in manifest.documents:
        path = (root / relative).resolve()
        if not path.is_relative_to(root / "documents") or path.suffix != ".md":
            raise ValueError("Manifest paths must stay inside the documents directory")
        if path in seen_paths:
            raise ValueError("Duplicate document path")
        seen_paths.add(path)
        text = path.read_text(encoding="utf-8")
        if not text.startswith("+++\n"):
            raise ValueError(f"Missing TOML metadata: {relative}")
        frontmatter, separator, body = text[4:].partition("\n+++\n")
        if not separator:
            raise ValueError(f"Unclosed metadata: {relative}")
        metadata = Metadata.model_validate(tomllib.loads(frontmatter))
        if metadata.key in seen_keys:
            raise ValueError(f"Duplicate document version: {metadata.key}")
        seen_keys.add(metadata.key)
        if "Document synthétique" not in body or len(body.split()) < 120:
            raise ValueError(f"Missing disclosure or insufficient document content: {relative}")
        documents.append(Document(metadata=metadata, body=body.strip(), relative_path=relative))
    if not documents:
        raise ValueError("Corpus cannot be empty")
    return documents


def validate_benchmark(documents: list[Document], path: Path) -> dict:
    """Check source support and permissions, not the semantic correctness of an answer."""
    benchmark = Benchmark.model_validate(read_json(path)).model_dump(mode="json")
    indexed = {document.metadata.key: document for document in documents}
    questions = benchmark["questions"]
    ids = set()
    counts = {"answer": 0, "abstain": 0, "deny": 0}
    for question in questions:
        if question["id"] in ids:
            raise ValueError("Duplicate question ID")
        ids.add(question["id"])
        behavior = question["expected_behavior"]
        counts[behavior] += 1
        relevant = question["relevant_documents"]
        if bool(relevant) != (behavior == "answer") or len(set(relevant)) != len(relevant):
            raise ValueError("Only answerable questions may have relevant documents")
        visible = {
            document.metadata.key
            for document in documents
            if document.visible_to(
                question["tenant_id"], set(question["roles"]), date.fromisoformat(question["as_of"])
            )
        }
        if not set(relevant).issubset(visible):
            raise ValueError(f"Reference includes an inaccessible document: {question['id']}")
        evidence_documents = set()
        for evidence in question["evidence"]:
            key = evidence["document"]
            if key not in relevant or evidence["quote"] not in indexed[key].body:
                raise ValueError(f"Unsupported reference evidence: {question['id']}")
            evidence_documents.add(key)
        if evidence_documents != set(relevant):
            raise ValueError("Every relevant document needs an exact supporting passage")
        for key in question.get("forbidden_documents", []):
            if key not in indexed or key in visible:
                raise ValueError("Forbidden reference must exist and be inaccessible")
    return {"questions": len(questions), **counts}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("data/knowledge"))
    parser.add_argument("--benchmark", type=Path, default=Path("data/evaluation/reference.json"))
    args = parser.parse_args()
    documents = load_corpus(args.root)
    if (
        read_json(args.root / "manifest.json")["corpus_id"]
        != read_json(args.benchmark)["corpus_id"]
    ):
        raise ValueError("Corpus and benchmark versions do not match")
    result = validate_benchmark(documents, args.benchmark)
    print(json.dumps({"documents": len(documents), "origin": "synthetic", **result}, indent=2))


if __name__ == "__main__":
    main()
