"""One-command release verification with machine-readable results.

Runs every release gate from a checkout, writes one log per gate plus ``summary.json``
and ``SUMMARY.md`` to ``docs/v06/evidence`` (override with ``EASY_EVIDENCE_DIR``), and
exits non-zero if any executed gate fails. Gates whose prerequisites are missing are
recorded as ``blocked`` with the reason, never as passed.

Usage (from the repository root, with the backend virtualenv active):

    python scripts/verify_release.py                 # everything available here
    python scripts/verify_release.py --skip-browser  # no Chromium
    python scripts/verify_release.py --only lint,backend-neural

Never deploys, pushes, or touches an application database.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = Path(os.environ.get("EASY_EVIDENCE_DIR", ROOT / "docs/v06/evidence"))
EVAL = ROOT / "docs/v06/evaluations"
PY = sys.executable


def gates() -> list[dict]:
    neural = {"EASY_RUN_NEURAL": "1", "HF_HUB_DISABLE_XET": "1"}
    pg_admin = os.environ.get("EASY_TEST_POSTGRES_ADMIN_URL")
    is_root = hasattr(os, "geteuid") and os.geteuid() == 0
    docker = (
        shutil.which("docker")
        and subprocess.run(["docker", "info"], capture_output=True).returncode == 0
    )
    browser = ["CHROMIUM_PATH"] if not shutil.which("node") else []

    def rental(name: str, dataset: str, *extra: str) -> dict:
        return dict(
            name=name,
            cwd="backend",
            cmd=[
                PY,
                "rental_eval.py",
                "--dataset",
                f"evaluation/{dataset}",
                "--out",
                str(EVAL / f"{name}.json"),
                *extra,
            ],
        )

    return [
        dict(name="lint", cwd=".", cmd=[PY, "-m", "ruff", "check", "backend", "scripts"]),
        dict(
            name="format",
            cwd=".",
            cmd=[PY, "-m", "ruff", "format", "--check", "backend", "scripts"],
        ),
        dict(
            name="backend-neural",
            cwd="backend",
            env=neural,
            cmd=[PY, "-m", "pytest", "-q", f"--junitxml={OUT}/backend-neural.xml"],
        ),
        dict(
            name="backend-postgres",
            cwd="backend",
            env={"EASY_TEST_POSTGRES_ADMIN_URL": pg_admin or ""},
            cmd=[PY, "-m", "pytest", "-q", f"--junitxml={OUT}/backend-postgres.xml"],
            blocked=None
            if pg_admin
            else "Set EASY_TEST_POSTGRES_ADMIN_URL to a disposable admin connection",
        ),
        dict(name="migrations-sqlite", cwd=".", cmd=[PY, "scripts/verify_sqlite_upgrade.py"]),
        dict(
            name="migrations-postgres",
            cwd=".",
            cmd=[PY, "scripts/verify_postgres.py"],
            blocked="initdb refuses to run as root; run this gate as a non-root user"
            if is_root
            else None,
        ),
        dict(
            name="eval-legacy-tasks",
            cwd="backend",
            cmd=[PY, "evaluate.py", "tasks", "--output", str(EVAL)],
        ),
        rental("eval-rental-holdout", "rentals_holdout.json"),
        rental("eval-comparison-v5", "rental_comparison_v5.json"),
        rental("eval-heldout-v051", "holdout_v051.json"),
        # Comparison set: the offline grammar is expected to miss natural phrasings, so this
        # suite gates on safety invariants and reports task success separately.
        rental("eval-release-v06", "release_v06.json", "--gate", "safety"),
        dict(
            name="eval-provider-fault",
            cwd="backend",
            cmd=[
                PY,
                "rental_eval.py",
                "--provider-fault",
                "--dataset",
                "evaluation/rental_fault_v5.json",
                "--out",
                str(EVAL / "eval-provider-fault.json"),
            ],
        ),
        rental("eval-release-v06-live", "release_v06.json", "--live", "--gate", "safety"),
        dict(
            name="eval-retrieval-4way",
            cwd="backend",
            env=neural,
            cmd=[PY, "evaluate.py", "retrieval", "--rerank", "--output", str(EVAL)],
        ),
        dict(name="frontend-typecheck", cwd="frontend", cmd=["npm", "run", "typecheck"]),
        dict(name="frontend-build", cwd="frontend", cmd=["npm", "run", "build"]),
        dict(
            name="browser-rental",
            cwd=".",
            cmd=[PY, "scripts/rental_browser.py"],
            browser=True,
            env={"REQUEST_LIMIT_PER_MINUTE": "300"},
        ),
        dict(name="browser-legacy", cwd=".", cmd=[PY, "scripts/browser_e2e.py"], browser=True),
        dict(
            name="browser-flagship", cwd=".", cmd=[PY, "scripts/flagship_browser.py"], browser=True
        ),
        dict(name="secret-scan", cwd=".", cmd=[PY, "scripts/scan_secrets.py"]),
        dict(name="audit-npm", cwd="frontend", cmd=["npm", "audit", "--omit=dev"]),
        dict(
            name="audit-python",
            cwd=".",
            cmd=[
                PY,
                "-m",
                "pip_audit",
                "--disable-pip",
                "--no-deps",
                "-r",
                "backend/requirements.lock",
            ],
            blocked=None
            if shutil.which("pip-audit") or _has_module("pip_audit")
            else "pip-audit not installed",
        ),
        dict(
            name="compose-persistence",
            cwd=".",
            cmd=[PY, "scripts/verify_compose.py"],
            blocked=None if docker else "Docker daemon unavailable",
        ),
    ] + ([] if not browser else [])


def _has_module(name: str) -> bool:
    from importlib.util import find_spec

    return find_spec(name) is not None


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--only", help="Comma-separated gate names")
    parser.add_argument("--skip-browser", action="store_true")
    parser.add_argument("--skip-compose", action="store_true")
    args = parser.parse_args()
    if os.environ.get("DATABASE_URL"):
        raise SystemExit(
            "Unset DATABASE_URL before verification; every gate owns a disposable database."
        )
    OUT.mkdir(parents=True, exist_ok=True)
    EVAL.mkdir(parents=True, exist_ok=True)
    selected = set(args.only.split(",")) if args.only else None

    results = []
    for gate in gates():
        name = gate["name"]
        if selected and name not in selected:
            continue
        if args.skip_browser and gate.get("browser"):
            gate["blocked"] = "Skipped with --skip-browser"
        if args.skip_compose and name == "compose-persistence":
            gate["blocked"] = "Skipped with --skip-compose"
        record = {
            "name": name,
            "command": [Path(c).name if c == PY else c for c in gate["cmd"]],
            "cwd": gate["cwd"],
        }
        if gate.get("blocked"):
            record.update(status="blocked", reason=gate["blocked"])
        else:
            env = {**os.environ, **{k: v for k, v in gate.get("env", {}).items() if v}}
            env["EASY_EVIDENCE_DIR"] = str(OUT)
            started = time.monotonic()
            with (OUT / f"{name}.log").open("w") as log:
                proc = subprocess.run(
                    gate["cmd"],
                    cwd=ROOT / gate["cwd"],
                    env=env,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                )
            status = "passed" if proc.returncode == 0 else "failed"
            # The output file is the value after "--out"/"--output" (the dataset is also a .json).
            flags = [str(c) for c in gate["cmd"]]
            output = next(
                (Path(flags[i + 1]) for i, c in enumerate(flags[:-1]) if c == "--out"), None
            )
            if (
                output
                and output.exists()
                and json.loads(output.read_text()).get("status") == "unexecuted"
            ):
                status = "unexecuted"
                record["reason"] = json.loads(output.read_text()).get("reason")
            record.update(
                status=status,
                exit_code=proc.returncode,
                seconds=round(time.monotonic() - started, 1),
                log=f"{name}.log",
            )
        results.append(record)
        print(f"{record['status']:>8}  {name}", flush=True)

    if selected and (OUT / "summary.json").exists():
        # Re-running selected gates replaces only their entries in the existing summary.
        previous = json.loads((OUT / "summary.json").read_text())
        rerun = {r["name"]: r for r in results}
        results = [rerun.pop(r["name"], r) for r in previous] + list(rerun.values())
    (OUT / "summary.json").write_text(json.dumps(results, indent=2))
    lines = ["| Gate | Status | Seconds | Note |", "|---|---|---|---|"]
    for r in results:
        lines.append(
            f"| {r['name']} | {r['status']} | {r.get('seconds', '')} | {r.get('reason', '')} |"
        )
    (OUT / "SUMMARY.md").write_text("\n".join(lines) + "\n")
    return int(any(r["status"] == "failed" for r in results))


if __name__ == "__main__":
    sys.exit(main())
