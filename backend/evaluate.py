"""Versioned evaluation; outputs per-case data, dataset hashes and honest execution modes."""

import argparse
import hashlib
import json
import math
import os
import statistics
import tempfile
import time
from datetime import UTC
from pathlib import Path

import numpy as np
from app.config import settings
from app.preferences import deterministic_plan, resolve
from app.rag import PolicyIndex, accepted_rental, identity
from app.schemas import Search

ROOT = Path(__file__).resolve().parent


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def percentiles(values):
    return (
        {"p50_ms": float(np.percentile(values, 50)), "p95_ms": float(np.percentile(values, 95))}
        if values
        else {}
    )


def retrieval(out, rerank):
    dataset = ROOT / "evaluation/rental_retrieval.json"
    data = json.loads(dataset.read_text())
    index = PolicyIndex()
    index.ingest(json.loads((ROOT / "corpus/synthetic_policies.json").read_text()))
    manifest, _ = index.load()
    valid = {c["chunk_id"]: c for c in manifest["chunks"]}
    variants = [("lexical", False), ("dense", False), ("hybrid", False)] + (
        [("hybrid", True)] if rerank else []
    )
    facet_file = ROOT / "evaluation/policy_facets_v5.json"
    facets = json.loads(facet_file.read_text())
    rubric_path = ROOT / "evaluation/policy_support_rubric_v5.json"
    rubric = json.loads(rubric_path.read_text())
    facet_rows = []
    from app.rental_evidence import assess

    rows = []
    summary = {}
    for strategy, reranking in variants:
        name = "reranked" if reranking else strategy
        for case in data["cases"]:
            rental = int(case["id"][1:]) >= 23
            start = time.perf_counter()
            hits = index.retrieve(
                case["query"],
                k=3,
                strategy=strategy,
                topic="rental" if rental else case.get("filter"),
                rerank=reranking,
            )
            docs = list(dict.fromkeys(h["doc_id"] for h in hits))
            expected = set(case["relevant"])
            matched = expected & set(docs)
            rank = next((i + 1 for i, d in enumerate(docs) if d in expected), None)
            dcg = sum(1 / math.log2(i + 2) for i, d in enumerate(docs) if d in expected)
            idcg = sum(1 / math.log2(i + 2) for i in range(min(3, len(expected))))
            supported = any(
                case.get("support") and case["support"].lower() in h["text"].lower() for h in hits
            )
            accepted = (
                accepted_rental(case["query"], hits)
                if rental
                else [h for h in hits if h["dense_score"] >= settings.rag_min_similarity]
            )
            rows.append(
                {
                    "scope": "rental" if rental else "legacy",
                    "accepted_docs": [h["doc_id"] for h in accepted],
                    "id": case["id"],
                    "configuration": name,
                    "query": case["query"],
                    "filter": case.get("filter"),
                    "expected_docs": case["relevant"],
                    "retrieved": [
                        {
                            "doc_id": h["doc_id"],
                            "chunk_id": h["chunk_id"],
                            "score": h["score"],
                            "dense_score": h["dense_score"],
                        }
                        for h in hits
                    ],
                    "recall_at_3": len(matched) / len(expected) if expected else None,
                    "mrr": 1 / rank if rank else 0,
                    "ndcg_at_3": dcg / idcg if idcg else None,
                    "citation_valid": all(
                        h["chunk_id"] in valid and h["text"] == valid[h["chunk_id"]]["text"]
                        for h in hits
                    ),
                    "expected_phrase_in_top3": supported if expected else None,
                    "accepted_answer_supported": all(
                        any(
                            h["doc_id"] == doc and phrase.lower() in h["text"].lower()
                            for h in accepted
                        )
                        for doc, phrase in case.get("required_support", {}).items()
                    )
                    if expected
                    else not accepted,
                    "abstained": not accepted,
                    "negative_abstention_correct": not accepted if not expected else None,
                    "latency_ms": round((time.perf_counter() - start) * 1000, 3),
                }
            )
        for case in facets:
            start = time.perf_counter()
            hits = index.retrieve(
                case["query"], k=3, strategy=strategy, topic="rental", rerank=reranking
            )
            accepted, missing = assess(case["query"], hits)
            ranked = [h["doc_id"] for h in hits]
            emitted = {c["doc_id"] for c in accepted}
            wanted = set(case["accepted"])
            relevant = set(case["relevant"])
            rank = next((i + 1 for i, d in enumerate(ranked) if d in relevant), None)
            labels = rubric[case["id"]]
            matched_support = all(
                any(phrase.casefold() in c["text"].casefold() for c in accepted)
                for phrase in labels.get("support", [])
            )
            matched_gap = not labels.get("staff_detail") or any(
                labels["staff_detail"] in gap for gap in missing
            )
            facet_rows.append(
                dict(
                    **case,
                    expected_details=labels,
                    matched_support=matched_support,
                    matched_gap=matched_gap,
                    configuration=name,
                    ranked=ranked,
                    citations=accepted,
                    unresolved=missing,
                    support_correct=matched_support
                    and matched_gap
                    and emitted == wanted
                    and bool(missing) == case["needs_staff"],
                    false_accept=bool(emitted - wanted) or (case["needs_staff"] and not missing),
                    valid=all(c["text"] in valid[c["chunk_id"]]["text"] for c in accepted),
                    recall=len(set(ranked) & relevant) / len(relevant),
                    mrr=1 / rank if rank else 0,
                    latency_ms=(time.perf_counter() - start) * 1000,
                )
            )
        group = [r for r in rows if r["configuration"] == name]
        positive = [r for r in group if r["expected_docs"]]
        negative = [r for r in group if not r["expected_docs"]]
        summary[name] = {
            "executed": len(group),
            "positive_queries": len(positive),
            "negative_queries": len(negative),
            "recall_at_3": statistics.mean(r["recall_at_3"] for r in positive),
            "mrr": statistics.mean(r["mrr"] for r in positive),
            "ndcg_at_3": statistics.mean(r["ndcg_at_3"] for r in positive),
            "answer_support_accuracy": statistics.mean(
                r["accepted_answer_supported"] for r in group
            ),
            "citation_validity": statistics.mean(r["citation_valid"] for r in group),
            "expected_phrase_coverage": statistics.mean(
                r["expected_phrase_in_top3"] for r in positive
            ),
            "negative_abstention_accuracy": statistics.mean(
                r["negative_abstention_correct"] for r in negative
            ),
            **percentiles([r["latency_ms"] for r in group]),
        }
        for scope in ["rental", "legacy"]:
            subset = [r for r in group if r["scope"] == scope]
            pos = [r for r in subset if r["expected_docs"]]
            neg = [r for r in subset if not r["expected_docs"]]
            summary[name][scope] = {
                "queries": len(subset),
                "positive": len(pos),
                "negative": len(neg),
                "support": statistics.mean(r["accepted_answer_supported"] for r in pos),
                "false_accepts": sum(not r["abstained"] for r in neg),
                "citation_validity": statistics.mean(r["citation_valid"] for r in subset),
                **{
                    m: statistics.mean(r[m] for r in pos)
                    for m in ["mrr", "recall_at_3", "ndcg_at_3"]
                },
                **percentiles([r["latency_ms"] for r in subset]),
            }
    result = {
        "dataset_hash": digest(dataset),
        "corpus_hash": digest(ROOT / "corpus/synthetic_policies.json"),
        "unique_scenarios": len(data["cases"]),
        "executed_examples": len(rows),
        "embedding": identity(),
        "reranker": {"model": settings.reranker_model, "revision": settings.reranker_revision}
        if rerank
        else None,
        "mode": "actual_local_neural_models",
        "llm_calls": 0,
        "cost_usd": None,
        "summary": summary,
        "cases": rows,
        "limits": "Authored small corpus, document-level binary judgments; phrase coverage is not an LLM semantic groundedness score. Latencies include cold initialization where incurred.",
    }
    result["facet_dataset_sha256"] = digest(facet_file)
    result["facet_rubric_sha256"] = digest(rubric_path)
    result["facet_cases"] = facet_rows
    result["facet_summary"] = {}
    for name in summary:
        subset = [r for r in facet_rows if r["configuration"] == name]
        result["facet_summary"][name] = dict(
            questions=len(subset),
            correct=sum(r["support_correct"] for r in subset),
            false_accepts=sum(r["false_accept"] for r in subset),
            needs_staff=sum(r["needs_staff"] for r in subset),
            valid_citations=sum(len(r["citations"]) for r in subset if r["valid"]),
            citations=sum(len(r["citations"]) for r in subset),
            recall_at_3=statistics.mean(r["recall"] for r in subset),
            mrr=statistics.mean(r["mrr"] for r in subset),
            **percentiles([r["latency_ms"] for r in subset]),
        )
    (out / "retrieval.json").write_text(json.dumps(result, indent=2))
    print(json.dumps(summary, indent=2))
    if any(r["false_accept"] or not r["valid"] for r in facet_rows):
        raise SystemExit(1)
    if any(m["citation_validity"] < 1 or m["recall_at_3"] < 0.8 for m in summary.values()):
        raise SystemExit(1)


def tasks(out):
    # API evaluation uses a new isolated SQLite DB. Never reads/writes an application DB.
    if os.environ.get("DATABASE_URL"):
        raise SystemExit("Unset DATABASE_URL; task evaluator allocates its own disposable database")
    temporary = tempfile.TemporaryDirectory(prefix="easy_eval_")
    os.environ["DATABASE_URL"] = "sqlite:///" + str(Path(temporary.name) / "eval.db")
    settings.database_url = os.environ["DATABASE_URL"]
    from datetime import datetime

    from app import clock
    from app.db import Base, engine
    from app.main import app
    from app.seed import seed
    from fastapi.testclient import TestClient

    clock.utcnow = lambda: datetime(2030, 6, 1, 15, tzinfo=UTC)
    Base.metadata.create_all(engine)
    seed()
    dataset = Path(os.getenv("EASY_TASK_DATASET", ROOT / "evaluation/tasks_v1.json"))
    data = json.loads(dataset.read_text())
    rows = []
    with TestClient(app) as client:
        for c in data["cases"]:
            start = time.perf_counter()
            kind = c["kind"]
            passed = False
            detail = {}
            if kind in {"preferences", "clarify"}:
                prefs = {}
                intent = None
                for text in c["turns"]:
                    plan = deterministic_plan(text)
                    intent = plan.intent
                    prefs = resolve(prefs, plan.updates).model_dump()
                passed = (
                    intent == c["expected"]
                    if kind == "clarify"
                    else all(prefs[k] == v for k, v in c["expected"].items())
                )
                detail = {"preferences": prefs, "intent": intent}
            elif kind in {"tool", "unsupported_confirmation", "injection"}:
                plan = deterministic_plan(c["query"])
                names = [t.name for t in plan.tools]
                passed = c["expected"] in names or plan.intent == c["expected"]
                detail = {"intent": plan.intent, "tools": [t.model_dump() for t in plan.tools]}
            elif kind == "ranking":
                from app.db import SessionLocal
                from app.services import inventory

                with SessionLocal() as db:
                    records = inventory(db, Search(**c["preferences"]))
                ids = [r["id"] for r in records]
                passed = (
                    (bool(ids) and ids[0] == c["expected_top"])
                    if "expected_top" in c
                    else set(ids) == set(c["expected_ids"])
                )
                detail = {
                    "ranked_ids": ids,
                    "hard_constraint_satisfaction": all(
                        (
                            c["preferences"].get("max_price") is None
                            or r["price"] <= c["preferences"]["max_price"]
                        )
                        and r["available"]
                        for r in records
                    ),
                }
            else:
                s = client.post("/sessions").json()
                h = {"X-Session-Token": s["token"]}
                base = "/sessions/" + s["id"]
                reply = client.post(base + "/chat", headers=h, json={"message": c["query"]}).json()
                if kind == "grounding":
                    passed = not reply["actions"]
                    detail = {"actions": reply["actions"]}
                else:
                    vid = reply["vehicles"][0]["id"]
                    slot = client.get("/availability/" + str(vid)).json()[0]
                    p = client.post(
                        base + "/proposals",
                        headers=h,
                        json={
                            "kind": "booking",
                            "arguments": {
                                "vehicle_id": vid,
                                "starts_at": datetime.fromtimestamp(slot, UTC).isoformat(),
                            },
                        },
                    ).json()
                    result = client.post(
                        base + "/proposals/" + p["id"] + "/confirm",
                        headers={**h, "Idempotency-Key": c["id"]},
                        json={"kind": p["kind"], "arguments": p["arguments"]},
                    ).json()
                    cancel = client.delete(
                        base + "/appointments/" + result["record_id"],
                        headers={**h, "Idempotency-Key": c["id"] + "-cancel"},
                    )
                    passed = result.get("committed") is True and cancel.status_code == 204
                    detail = {
                        "record_id": result.get("record_id"),
                        "cancel_status": cancel.status_code,
                    }
            rows.append(
                {
                    "id": c["id"],
                    "kind": kind,
                    "pass": bool(passed),
                    "detail": detail,
                    "latency_ms": round((time.perf_counter() - start) * 1000, 3),
                }
            )
    result = {
        "dataset_hash": digest(dataset),
        "mode": "deterministic_and_real_local_sql",
        "unique_scenarios": len(data["cases"]),
        "executed_examples": len(rows),
        "passed": sum(r["pass"] for r in rows),
        "failed": sum(not r["pass"] for r in rows),
        "skipped": 0,
        "llm_calls": 0,
        "cost_usd": None,
        **percentiles([r["latency_ms"] for r in rows]),
        "cases": rows,
    }
    (out / "tasks.json").write_text(json.dumps(result, indent=2))
    print(json.dumps({k: v for k, v in result.items() if k != "cases"}, indent=2))
    engine.dispose()
    temporary.cleanup()
    if result["failed"]:
        raise SystemExit(1)


async def live(out):
    from app.provider import plan

    data = json.loads((ROOT / "evaluation/tasks_v1.json").read_text())
    cases = []
    for c in data["cases"]:
        if "query" not in c:
            continue
        start = time.perf_counter()
        try:
            result, trace = await plan(c["query"], {}, [])
            cases.append(
                {
                    "id": c["id"],
                    "plan": result.model_dump(),
                    "trace": trace,
                    "latency_ms": (time.perf_counter() - start) * 1000,
                }
            )
        except Exception as e:
            cases.append({"id": c["id"], "error": type(e).__name__})
    (out / "live.json").write_text(
        json.dumps(
            {
                "mode": "live_provider",
                "dataset_hash": digest(ROOT / "evaluation/tasks_v1.json"),
                "cases": cases,
                "limits": "Diagnostic plans only; no quality score inferred without expected live-plan judgments.",
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("suite", choices=["retrieval", "tasks", "live"])
    parser.add_argument("--rerank", action="store_true")
    parser.add_argument("--output", default="../docs/v02/evaluations")
    args = parser.parse_args()
    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)
    if args.suite == "retrieval":
        with tempfile.TemporaryDirectory(prefix="easy_eval_index_") as directory:
            settings.rag_path = directory
            retrieval(out, args.rerank)
    elif args.suite == "tasks":
        tasks(out)
    elif not settings.openai_api_key or not settings.openai_model:
        (out / "live.json").write_text(
            json.dumps(
                {
                    "status": "unexecuted",
                    "reason": "No live provider credentials/model configured",
                    "model_calls": 0,
                },
                indent=2,
            )
        )
    else:
        __import__("asyncio").run(live(out))
