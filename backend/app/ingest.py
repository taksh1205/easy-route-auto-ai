import argparse
import json
from pathlib import Path

from .rag import PolicyIndex


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--file",
        default=str(Path(__file__).resolve().parents[1] / "corpus/synthetic_policies.json"),
    )
    args = parser.parse_args()
    path = Path(args.file)
    if path.stat().st_size > 256000:
        raise SystemExit("Corpus file exceeds 256KB")
    print(json.dumps(PolicyIndex().ingest(json.loads(path.read_text())), indent=2))


if __name__ == "__main__":
    main()
