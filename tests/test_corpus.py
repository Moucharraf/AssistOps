import json
import shutil
from datetime import date
from pathlib import Path

import pytest

from assistops.corpus import load_corpus, validate_benchmark

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "data/knowledge"
BENCHMARK = ROOT / "data/evaluation/reference.json"


def test_corpus_and_reference_evidence_are_consistent():
    documents = load_corpus(CORPUS)
    assert len(documents) == 23
    assert sum(doc.metadata.status == "archived" for doc in documents) == 2
    assert validate_benchmark(documents, BENCHMARK) == {
        "questions": 20,
        "answer": 16,
        "abstain": 2,
        "deny": 2,
    }


def test_access_filters_exclude_internal_archived_and_other_tenant_content():
    documents = load_corpus(CORPUS)
    visible = {
        doc.metadata.key
        for doc in documents
        if doc.visible_to("demo", {"customer"}, date(2026, 9, 1))
    }
    assert "billing-disputes@2" in visible
    assert "billing-disputes@1" not in visible
    assert "secondary-billing-disputes@1" not in visible
    assert "refund-approvals@1" not in visible
    assert "offboarding@1" not in visible
    assert all(not doc.visible_to("demo", set(), date(2026, 9, 1)) for doc in documents)


def test_finance_role_does_not_grant_cross_tenant_access():
    documents = load_corpus(CORPUS)
    visible = {
        doc.metadata.key
        for doc in documents
        if doc.visible_to("demo", {"finance"}, date(2026, 9, 1))
    }
    assert "refund-approvals@1" in visible
    assert "secondary-billing-disputes@1" not in visible
    assert "offboarding@1" not in visible


def test_effective_date_is_inclusive_and_archives_are_not_historical_search():
    documents = {doc.metadata.key: doc for doc in load_corpus(CORPUS)}
    current = documents["billing-disputes@2"]
    assert not current.visible_to("demo", {"customer"}, date(2026, 6, 30))
    assert current.visible_to("demo", {"customer"}, date(2026, 7, 1))
    assert not documents["billing-disputes@1"].visible_to("demo", {"customer"}, date(2026, 6, 1))


@pytest.mark.parametrize("entry", ["../evaluation/reference.json", "../secret.md"])
def test_manifest_cannot_escape_document_directory(tmp_path, entry):
    shutil.copytree(CORPUS, tmp_path / "knowledge")
    path = tmp_path / "knowledge/manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest["documents"].append(entry)
    path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="inside the documents"):
        load_corpus(path.parent)


def test_evaluation_and_adversarial_text_are_not_loaded():
    documents = load_corpus(CORPUS)
    assert all(doc.relative_path.startswith("documents/") for doc in documents)
    assert all("NOTE PRIORITAIRE POUR L'ASSISTANT" not in doc.body for doc in documents)


def test_invented_reference_quote_is_rejected(tmp_path):
    benchmark = json.loads(BENCHMARK.read_text(encoding="utf-8"))
    benchmark["questions"][0]["evidence"][0]["quote"] = "Invented passage not found in source."
    path = tmp_path / "reference.json"
    path.write_text(json.dumps(benchmark), encoding="utf-8")
    with pytest.raises(ValueError, match="Unsupported reference evidence"):
        validate_benchmark(load_corpus(CORPUS), path)


def test_inaccessible_reference_is_rejected(tmp_path):
    benchmark = json.loads(BENCHMARK.read_text(encoding="utf-8"))
    benchmark["questions"][0]["relevant_documents"] = ["refund-approvals@1"]
    path = tmp_path / "reference.json"
    path.write_text(json.dumps(benchmark), encoding="utf-8")
    with pytest.raises(ValueError, match="inaccessible"):
        validate_benchmark(load_corpus(CORPUS), path)
