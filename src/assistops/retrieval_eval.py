"""Score document rankings; this module never generates answers or performs retrieval."""

import argparse
import json
from datetime import date
from pathlib import Path

from assistops.corpus import load_corpus, read_json, validate_benchmark


def score_rankings(documents, benchmark, predictions, k: int = 5) -> dict:
    if k < 1:
        raise ValueError("k must be positive")
    if predictions["corpus_id"] != benchmark["corpus_id"]:
        raise ValueError("Rankings and benchmark must target the same corpus")
    questions = {question["id"]: question for question in benchmark["questions"]}
    indexed = {document.metadata.key: document for document in documents}
    rankings = {}
    for ranking in predictions["rankings"]:
        key = ranking["question_id"]
        if key in rankings:
            raise ValueError("Duplicate ranking for a question")
        ranked = ranking["documents"]
        if not isinstance(ranked, list) or not all(isinstance(item, str) for item in ranked):
            raise ValueError("Rankings must contain a list of document version keys")
        if len(ranked) != len(set(ranked)) or not set(ranked).issubset(indexed):
            raise ValueError("Rankings must contain distinct known document versions")
        rankings[key] = ranked
    if set(rankings) != set(questions):
        raise ValueError("Provide one ranking for every question; partial reports are rejected")
    recalls = []
    cases = []
    for key, question in questions.items():
        top = rankings[key][:k]
        expected = set(question["relevant_documents"])
        # Unanswerable and forbidden requests have no recall denominator; track them separately.
        recall = len(expected.intersection(top)) / len(expected) if expected else None
        if recall is not None:
            recalls.append(recall)
        # Do not filter invalid hits here: doing so would conceal a retrieval access-control bug.
        ineligible = [
            item
            for item in top
            if not indexed[item].visible_to(
                question["tenant_id"], set(question["roles"]), date.fromisoformat(question["as_of"])
            )
        ]
        cases.append({"question_id": key, "recall": recall, "ineligible_hits": ineligible})
    return {
        "metric": f"document_recall@{k}",
        "macro_recall": sum(recalls) / len(recalls) if recalls else None,
        "answerable_questions": len(recalls),
        "excluded_from_recall": len(cases) - len(recalls),
        "queries_with_ineligible_hits": sum(bool(case["ineligible_hits"]) for case in cases),
        "cases": cases,
        "scope": "retrieval_only_on_synthetic_reference_set",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("predictions", type=Path)
    parser.add_argument("--root", type=Path, default=Path("data/knowledge"))
    parser.add_argument("--benchmark", type=Path, default=Path("data/evaluation/reference.json"))
    args = parser.parse_args()
    documents = load_corpus(args.root)
    validate_benchmark(documents, args.benchmark)
    benchmark = read_json(args.benchmark)
    if read_json(args.root / "manifest.json")["corpus_id"] != benchmark["corpus_id"]:
        raise ValueError("Corpus and benchmark versions do not match")
    print(json.dumps(score_rankings(documents, benchmark, read_json(args.predictions)), indent=2))


if __name__ == "__main__":
    main()
