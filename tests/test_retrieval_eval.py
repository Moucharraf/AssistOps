from pathlib import Path

import pytest

from assistops.corpus import load_corpus, read_json
from assistops.retrieval_eval import score_rankings

ROOT = Path(__file__).resolve().parents[1]


def fixtures():
    documents = load_corpus(ROOT / "data/knowledge")
    benchmark = read_json(ROOT / "data/evaluation/reference.json")
    # Oracle rankings verify the arithmetic only; they are not retrieval performance results.
    predictions = {
        "corpus_id": benchmark["corpus_id"],
        "rankings": [
            {"question_id": q["id"], "documents": list(q["relevant_documents"])}
            for q in benchmark["questions"]
        ],
    }
    return documents, benchmark, predictions


def test_known_perfect_rankings_and_excluded_cases():
    report = score_rankings(*fixtures())
    assert report["macro_recall"] == 1
    assert report["answerable_questions"] == 16
    assert report["excluded_from_recall"] == 4
    assert report["queries_with_ineligible_hits"] == 0


def test_missing_one_of_two_sources_has_half_recall():
    documents, benchmark, predictions = fixtures()
    predictions["rankings"][12]["documents"].pop()
    report = score_rankings(documents, benchmark, predictions)
    assert report["cases"][12]["recall"] == 0.5
    assert report["macro_recall"] == (15 + 0.5) / 16


def test_rank_six_is_not_a_hit():
    documents, benchmark, predictions = fixtures()
    predictions["rankings"][0]["documents"] = [
        "plans@1",
        "retention@1",
        "data-export@1",
        "password-reset@1",
        "ticket-creation@1",
        "billing-disputes@2",
    ]
    assert score_rankings(documents, benchmark, predictions)["cases"][0]["recall"] == 0


def test_ineligible_hit_is_reported_even_when_recall_is_perfect():
    documents, benchmark, predictions = fixtures()
    predictions["rankings"][0]["documents"].append("billing-disputes@1")
    predictions["rankings"][18]["documents"] = ["refund-approvals@1"]
    report = score_rankings(documents, benchmark, predictions)
    assert report["macro_recall"] == 1
    assert report["queries_with_ineligible_hits"] == 2
    assert report["cases"][18]["recall"] is None


@pytest.mark.parametrize("bad", ["missing", "duplicate_question", "duplicate_document", "unknown"])
def test_invalid_rankings_fail_instead_of_inflating_scores(bad):
    documents, benchmark, predictions = fixtures()
    if bad == "missing":
        predictions["rankings"].pop()
    elif bad == "duplicate_question":
        predictions["rankings"].append(predictions["rankings"][0])
    elif bad == "duplicate_document":
        predictions["rankings"][0]["documents"] *= 2
    else:
        predictions["rankings"][0]["documents"] = ["unknown@1"]
    with pytest.raises(ValueError):
        score_rankings(documents, benchmark, predictions)
