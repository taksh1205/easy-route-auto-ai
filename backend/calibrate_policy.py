"""Select a rental-only cosine cutoff using document labels on the development split."""

import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

from app.rag import PolicyIndex


def main():
    with TemporaryDirectory() as temp:
        index = PolicyIndex(temp)
        index.ingest(json.loads(Path("corpus/synthetic_policies.json").read_text()))
        cases = []
        for query, labels in json.loads(Path("evaluation/rental_dev.json").read_text()):
            hits = index.retrieve(query, k=12)
            scores = {
                h["doc_id"]: h["dense_score"] for h in hits if h["topic"].startswith("rental_")
            }
            cases.append(dict(query=query, labels=labels, scores=scores))

        def errors(t):
            return sum(
                len(set(c["labels"]) ^ {k for k, v in c["scores"].items() if v >= t}) for c in cases
            )

        grid = [n / 100 for n in range(25, 56)]
        best = min(grid, key=lambda t: (errors(t), -t))
        Path(sys.argv[1]).write_text(
            json.dumps(
                dict(
                    cases=cases,
                    grid_errors={str(t): errors(t) for t in grid},
                    chosen=best,
                ),
                indent=2,
            )
        )


if __name__ == "__main__":
    main()
