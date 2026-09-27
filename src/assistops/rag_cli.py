"""Explicit operator commands for ingestion, scoped retrieval and reference evaluation."""

import argparse
import json
from datetime import date
from pathlib import Path

from assistops.config import Settings
from assistops.corpus import load_corpus, read_json, validate_benchmark
from assistops.embeddings import OpenAIEmbeddings
from assistops.retrieval import Retriever, chunk_documents
from assistops.retrieval_eval import score_rankings


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["plan", "ingest", "search", "evaluate"])
    parser.add_argument("--root", type=Path, default=Path("data/knowledge"))
    parser.add_argument("--alias", default="assistops_knowledge")
    parser.add_argument("--query")
    parser.add_argument("--tenant")
    parser.add_argument("--roles", nargs="+")
    parser.add_argument("--as-of", type=date.fromisoformat, default=date.today())
    parser.add_argument("--output", type=Path, default=Path(".cache/rag-report.json"))
    args = parser.parse_args()
    documents = load_corpus(args.root)
    chunks = chunk_documents(documents)
    if args.command == "plan":
        print(
            json.dumps(
                {
                    "documents": len(documents),
                    "chunks": len(chunks),
                    "input_utf8_bytes": sum(len(c.text.encode()) for c in chunks),
                    "external_calls": 0,
                },
                indent=2,
            )
        )
        return
    if args.command == "search" and not (args.query and args.tenant and args.roles):
        parser.error("search requires --query, --tenant and --roles (trusted operator context)")
    settings = Settings()
    embedder = OpenAIEmbeddings(settings)
    retriever = Retriever(settings, embedder, args.alias)
    try:
        if args.command == "ingest":
            report = retriever.ingest(documents)
        elif args.command == "search":
            report = {
                "sources": retriever.search(args.query, args.tenant, set(args.roles), args.as_of),
                "tokens_used": embedder.tokens_used,
            }
        else:
            benchmark_path = Path("data/evaluation/reference.json")
            validate_benchmark(documents, benchmark_path)
            benchmark = read_json(benchmark_path)
            manifest = read_json(args.root / "manifest.json")
            if manifest["corpus_id"] != benchmark["corpus_id"]:
                raise ValueError("Benchmark does not match corpus")
            predictions = {"corpus_id": benchmark["corpus_id"], "rankings": []}
            collection = retriever.pin_snapshot()
            # Only the question is embedded. Gold answers and evidence never enter retrieval.
            for question in benchmark["questions"]:
                sources = retriever.search(
                    question["question"],
                    question["tenant_id"],
                    set(question["roles"]),
                    date.fromisoformat(question["as_of"]),
                )
                predictions["rankings"].append(
                    {"question_id": question["id"], "documents": [s["document"] for s in sources]}
                )
            report = {
                "predictions": predictions,
                "evaluation": score_rankings(documents, benchmark, predictions),
                "model": embedder.vector_name,
                "collection": collection,
                "tokens_used": embedder.tokens_used,
            }
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False, indent=2))
    finally:
        retriever.close()
        embedder.close()


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        # Keep provider payloads, connection credentials and source text out of tracebacks.
        print(json.dumps({"error_type": type(exc).__name__, "status": "failed"}))
        raise SystemExit(1) from None
