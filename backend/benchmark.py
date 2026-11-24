"""Small deterministic extraction smoke benchmark; does not assess real LLM quality."""

import json
import time

from app.ai import deterministic_extract

CASES = [
    ("SUV under $25,000", {"max_price": 25000, "body": "suv"}),
    ("sedan below 20k", {"max_price": 20000, "body": "sedan"}),
    ("truck budget 30000", {"max_price": 30000, "body": "truck"}),
    ("hatchback max 22000", {"max_price": 22000, "body": "hatchback"}),
    ("7 seats", {"min_seats": 7}),
    ("SUV below 18k", {"max_price": 18000, "body": "suv"}),
    ("hello", {}),
    ("budget of $19,000", {"max_price": 19000}),
]
if __name__ == "__main__":
    started = time.perf_counter()
    results = []
    for query, expected in CASES:
        actual = deterministic_extract(query, {}).model_dump(exclude_defaults=True)
        results.append(
            {"query": query, "expected": expected, "actual": actual, "pass": actual == expected}
        )
    print(
        json.dumps(
            {
                "mode": "deterministic",
                "scope": "8 authored grammar smoke cases, no held-out model evaluation",
                "cases": results,
                "exact_match": sum(r["pass"] for r in results) / len(results),
                "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
                "model_calls": 0,
                "cost_usd": None,
            },
            indent=2,
        )
    )
