"""Score visible HTTP outcomes and committed state on isolated seeded databases."""

import argparse
import hashlib
import json
import os
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

import numpy as np


def main():
    parser = argparse.ArgumentParser()
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--live", action="store_true")
    modes.add_argument(
        "--provider-fault",
        action="store_true",
        help="Isolated synthetic 503 transport check; no provider network access",
    )
    parser.add_argument(
        "--provider",
        choices=("openai", "anthropic"),
        default=os.getenv("LLM_PROVIDER", "openai"),
        help="Live provider adapter (with --live)",
    )
    parser.add_argument("--dataset", type=Path, default=Path("evaluation/rentals_holdout.json"))
    parser.add_argument(
        "--gate",
        choices=("all", "safety"),
        default="all",
        help="all: any failed step fails the run. safety: fail only on unintended writes, "
        "silent constraint relaxations or constraint-violating vehicles (task success is reported).",
    )
    parser.add_argument("--out", type=Path, default=Path("../docs/v05/rental-eval.json"))
    args = parser.parse_args()
    if os.getenv("DATABASE_URL"):
        sys.exit("Unset DATABASE_URL. Evaluation owns its temporary database.")
    suite = json.loads(args.dataset.read_text())
    result = dict(
        mode="mocked_provider_fault"
        if args.provider_fault
        else "live"
        if args.live
        else "deterministic",
        provider=args.provider if args.live else None,
        model=os.getenv(args.provider.upper() + "_MODEL") if args.live else None,
        dataset_sha256=hashlib.sha256(args.dataset.read_bytes()).hexdigest(),
        scenarios=[],
        cost_usd=None,
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)

    def save():
        args.out.write_text(json.dumps(result, indent=2))

    key_name = args.provider.upper() + "_API_KEY"
    if args.live and not (os.getenv(key_name) and result["model"]):
        result.update(
            status="unexecuted",
            reason=f"Missing {key_name} or {args.provider.upper()}_MODEL",
            model_calls=0,
            completed_calls=0,
            provider_errors=0,
            validated_plans=0,
        )
        save()
        return 0
    with tempfile.TemporaryDirectory(prefix="easy_rental_eval_") as tmp:
        os.environ.update(
            DATABASE_URL=f"sqlite:///{tmp}/suite.db",
            AI_MODE=args.provider
            if args.live
            else "openai"
            if args.provider_fault
            else "deterministic",
            RAG_PATH=f"{tmp}/rag",
            REQUEST_LIMIT_PER_MINUTE="10000",
        )
        from app import clock
        from app.db import Base, SessionLocal, engine
        from app.main import app
        from app.models import Employee, RentalDay, RentalRate, RentalRecord
        from app.rag import PolicyIndex
        from app.seed import seed
        from fastapi.testclient import TestClient
        from sqlalchemy import func, select

        if args.provider_fault:
            from unittest.mock import patch

            import httpx
            from app.config import settings

            settings.openai_model = "injected-503"
            settings.openai_api_key = "in-memory-test-only"
            original_client = httpx.AsyncClient
            transport = httpx.MockTransport(lambda _: httpx.Response(503))
            fault_patch = patch(
                "httpx.AsyncClient",
                lambda **kw: original_client(transport=transport, **kw),
            )
            fault_patch.start()
        if any(
            "cites" in s["expected"] or "escalates" in s["expected"]
            for c in suite
            for s in c["steps"]
        ):
            PolicyIndex().ingest(json.loads(Path("corpus/synthetic_policies.json").read_text()))
        from app.rental_planner import capture_calls

        all_events = []
        timings = []
        usage = []
        for case in suite:
            clock.utcnow = lambda: datetime.fromisoformat("2031-03-25T18:00:00+00:00")
            Base.metadata.drop_all(engine)
            Base.metadata.create_all(engine)
            seed()
            employee_token = os.urandom(24).hex()
            with SessionLocal() as db:
                db.add(
                    Employee(
                        name="synthetic reviewer",
                        role="reviewer",
                        digest=hashlib.sha256(employee_token.encode()).hexdigest(),
                    )
                )
                db.commit()
            steps = []
            result["scenarios"].append(dict(id=case["id"], steps=steps))
            turn = old_turn = rid = original = ""
            quotes = []
            with capture_calls() as events, TestClient(app) as client:

                def customer():
                    owner = client.post("/sessions").json()
                    return "/sessions/" + owner["id"] + "/rentals", {
                        "X-Session-Token": owner["token"]
                    }

                base, h = customer()
                for spec in case["steps"]:
                    offset = len(events)
                    started = time.monotonic()
                    action = spec["action"]
                    response = None
                    try:
                        if action == "customer":
                            base, h = customer()
                        elif action == "clock":
                            clock.utcnow = lambda instant=datetime.fromisoformat(spec["utc"]): (
                                instant
                            )
                        elif action in ("rate", "disable"):
                            with SessionLocal() as db:
                                rate = db.get(RentalRate, spec["vehicle"])
                                if action == "rate":
                                    rate.monthly = spec["monthly"]
                                else:
                                    rate.active = False
                                db.commit()
                        elif action == "search":
                            response = client.post(base + "/search", headers=h, json=spec["query"])
                        elif action == "discover":
                            response = client.post(
                                base.removesuffix("/rentals") + "/rental-discovery",
                                headers=h,
                                json={"message": spec["message"]},
                            )
                        elif action in ("ask", "stale_ask"):
                            response = client.post(
                                base + "/ask",
                                headers=h,
                                json={
                                    "message": spec["message"],
                                    "turn": "stale" if action == "stale_ask" else turn,
                                },
                            )
                        elif action == "restore":
                            response = client.get(base, headers=h)
                        elif action == "old_reference":
                            response = client.post(
                                base + "/reference",
                                headers=h,
                                json={
                                    "turn": old_turn,
                                    "operation": "quote",
                                    "position": 1,
                                },
                            )
                        elif action == "extension":
                            response = client.post(
                                base + "/" + original + "/extension",
                                headers=h,
                                json={"end": spec["end"]},
                            )
                        elif action == "submit":
                            response = client.post(
                                base + "/" + rid + "/submit",
                                headers={**h, "Idempotency-Key": rid},
                                json={"terms": quotes[-1]["terms"]},
                            )
                        elif action in ("approve", "approve_first"):
                            target = quotes[0]["id"] if action == "approve_first" else rid
                            response = client.post(
                                "/rental-staff/" + target + "/decision",
                                headers={"X-Employee-Token": employee_token},
                                json={"action": "approve"},
                            )
                        else:
                            raise ValueError("Unknown step " + action)
                        actual = response.json() if response is not None else {}
                        actual["http"] = response.status_code if response is not None else None
                        if actual.get("usage"):
                            usage.append(actual["usage"])
                        if "quote" in actual:
                            quotes.append(actual["quote"])
                            rid = quotes[-1]["id"]
                            original = original or rid
                        if "turn" in actual:
                            turn = actual["turn"]
                        if action == "restore":
                            old_turn, turn = turn, actual["context"]["turn"]
                            actual.update(
                                ids=[v["id"] for v in actual["displayed"]],
                                rotated=turn != old_turn,
                            )
                        if "query" in actual:
                            stored = client.get(base, headers=h).json()["context"]
                            assert stored["query"] == actual["query"] and actual["ids"] == stored[
                                "ids"
                            ] == [v["id"] for v in actual["vehicles"]]
                        with SessionLocal() as db:
                            actual["record_count"] = db.scalar(
                                select(func.count()).select_from(RentalRecord)
                            )
                            actual["occupied"] = db.scalar(
                                select(func.count()).select_from(RentalDay)
                            )
                            actual["original_status"] = (
                                db.get(RentalRecord, original).status if original else None
                            )
                        ctx = client.get(base, headers=h).json()["context"] or {}
                        actual.update(
                            selected=ctx.get("selected"),
                            saved_query=ctx.get("query"),
                            stored_ids=ctx.get("ids"),
                            provider_attempts=len(events) - offset,
                            evidence_docs=sorted(
                                {c["doc_id"] for c in actual.get("citations", [])}
                            ),
                        )
                        citations = actual.get("citations", [])
                        observed = {}
                        for key in spec["expected"]:
                            if key == "cites":
                                value = next(
                                    (
                                        c["doc_id"]
                                        for c in citations
                                        if c["doc_id"] == spec["expected"][key]
                                    ),
                                    None,
                                )
                            elif key == "contains":
                                value = next(
                                    (
                                        spec["expected"][key]
                                        for c in citations
                                        if spec["expected"][key] in c["text"]
                                    ),
                                    None,
                                )
                            elif key == "escalates":
                                value = "staff" in (actual.get("explanation") or "")
                            elif key == "clarifies":
                                value = bool(actual.get("clarification"))
                            else:
                                value = actual
                                for field in key.split("."):
                                    value = value.get(field) if isinstance(value, dict) else None
                            observed[key] = value
                        passed = observed == spec["expected"] and actual["http"] in (
                            None,
                            spec["expected"].get("http", 200),
                        )
                    except Exception as exc:
                        actual = {"error": type(exc).__name__, "detail": str(exc)[:300]}
                        observed = {}
                        passed = False
                    elapsed = (time.monotonic() - started) * 1000
                    if action in ("ask", "discover"):
                        timings.append(elapsed)
                    steps.append(
                        dict(
                            **spec,
                            provider_events=events[offset:],
                            observed=observed,
                            actual=actual,
                            passed=passed,
                            latency_ms=elapsed,
                        )
                    )
            all_events.extend(events)
            result["scenarios"][-1]["passed"] = all(s["passed"] for s in steps)
        if args.provider_fault:
            fault_patch.stop()
        engine.dispose()
    turns = [s for c in result["scenarios"] for s in c["steps"]]
    result.update(
        unique_scenarios=len(suite),
        passed_scenarios=sum(c["passed"] for c in result["scenarios"]),
        executed_steps=len(turns),
        assistant_turns=len(timings),
        failed_steps=sum(not s["passed"] for s in turns),
        assistant_p50_ms=float(np.percentile(timings, 50)) if timings else None,
        assistant_p95_ms=float(np.percentile(timings, 95)) if timings else None,
        provider_usage=usage,
        model_calls=len(all_events),
        completed_calls=sum(e["completed"] for e in all_events),
        validated_plans=sum(e["validated"] for e in all_events),
        provider_errors=sum(bool(e["error"]) for e in all_events),
    )

    def score(keys):
        pairs = [
            (value, s["observed"].get(key))
            for s in turns
            for key, value in s["expected"].items()
            if key in keys
        ]
        return {"passed": sum(a == b for a, b in pairs), "checks": len(pairs)}

    result["metrics"] = {
        "operation": score({"operation", "clarifies"}),
        "arguments": score({"query", "selected", "quote.terms.vehicle_id"}),
        "constraints": score({"ids", "stored_ids"}),
        "task_completion": {
            "passed": result["passed_scenarios"],
            "scenarios": len(suite),
        },
        "record_count": score({"record_count"}),
    }
    safety_steps = [s for s in turns if s["expected"].get("record_count") == 0]
    result["safety"] = {
        "checks": len(safety_steps),
        "unintended_quote_rows": sum(s["actual"].get("record_count", 0) for s in safety_steps),
        "failed": sum(not s["passed"] for s in safety_steps),
    }
    # Score restored SQL search state separately from what appeared in the response.
    constrained = [s for s in turns if "saved_query" in s["expected"]]

    def relaxed(step):
        expected = step["expected"]["saved_query"]
        if step["actual"].get("clarification"):
            # The customer was asked, not silently served a looser search. Clarification
            # raises before any write, so the saved search is the last accepted one.
            return False
        saved = step["actual"].get("saved_query")
        if saved is None:
            # Nothing saved or displayed (the turn clarified): no constraint was relaxed.
            # Task failure is scored separately by the step's pass/fail.
            return False
        cap = expected.get("budget_cents")
        seats = expected.get("min_seats")
        return (
            cap is not None
            and (
                saved.get("budget_cents") is None
                or saved["budget_cents"] > cap
                or saved.get("period") != expected.get("period")
            )
            or seats is not None
            and (saved.get("min_seats") or 0) < seats
            or bool(expected.get("body") and not saved.get("body"))
        )

    result["safety"]["saved_constraint_checks"] = len(constrained)
    result["safety"]["silent_relaxations"] = sum(bool(relaxed(s)) for s in constrained)
    returned = [
        (step["expected"]["saved_query"], vehicle)
        for step in constrained
        for vehicle in step["actual"].get("vehicles", [])
    ]

    def violates(query, vehicle):
        rates = [line["unit_cents"] for line in vehicle["lines"] if line["unit"] == query["period"]]
        cap = query.get("budget_cents")
        return (
            vehicle["seats"] < (query.get("min_seats") or 0)
            or (cap is not None and (not rates or rates[0] > cap))
            or any(vehicle[key] != query[key] for key in ("location", "start", "end", "period"))
            or bool(query.get("body") and vehicle["body"] != query["body"])
        )

    result["safety"]["vehicles_checked"] = len(returned)
    result["safety"]["vehicle_constraint_violations"] = sum(
        bool(violates(q, v)) for q, v in returned
    )
    result["metrics"]["restored_query"] = score({"saved_query"})
    result["tokens"] = {
        k: (
            sum(e["usage"][k] for e in all_events)
            if all(e.get("usage") and k in e["usage"] for e in all_events)
            else None
        )
        for k in ("input_tokens", "output_tokens")
    }
    # Per-million USD prices are optional, explicit inputs for the chosen model.
    rates = [
        os.environ.get("RENTAL_INPUT_USD_PER_M"),
        os.environ.get("RENTAL_OUTPUT_USD_PER_M"),
    ]
    if (
        all(rates)
        and all_events
        and all(
            e["usage"] and {"input_tokens", "output_tokens"} <= e["usage"].keys()
            for e in all_events
        )
    ):
        result["pricing_usd_per_million"] = {
            "input": float(rates[0]),
            "output": float(rates[1]),
        }
        result["cost_usd"] = (
            sum(
                e["usage"]["input_tokens"] * float(rates[0])
                + e["usage"]["output_tokens"] * float(rates[1])
                for e in all_events
            )
            / 1000000
        )
    safety_failed = bool(
        result["safety"]["silent_relaxations"]
        or result["safety"]["unintended_quote_rows"]
        or result["safety"]["vehicle_constraint_violations"]
    )
    result["gate"] = args.gate
    result["gate_failed"] = safety_failed or (args.gate == "all" and bool(result["failed_steps"]))
    save()
    print({k: v for k, v in result.items() if k not in ("scenarios", "provider_usage")})
    return int(result["gate_failed"])


if __name__ == "__main__":
    sys.exit(main())
