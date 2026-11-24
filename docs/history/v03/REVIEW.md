# Rental release 0.3.0 · independent reviewer handoff

The exact baseline archive SHA-256 was 7d4b2326b2f3ef8ba1d3fb8139d90f53937b46d681bf7647f823d4240d9cb523. The new migration extends the existing SQL model. Original purchase values and appointment records retain their meaning. The rental experience uses a dedicated /rentals page and session-owned rental routes. The legacy explorer remains available at /.

## Verification matrix

| Area | Command or entry point | Exit | Observed evidence |
|---|---|---:|---|
| Backend, SQLite, real embeddings and cross-encoder-related integration | EASY_RUN_NEURAL=1 HF_HUB_OFFLINE=1 python -m pytest -q --junitxml=../docs/v03/tests.xml | 0 | 77 passed. See tests.log and tests.xml. Retrieval comparison separately executed the actual cross-encoder. |
| PostgreSQL 16.2 | python scripts/verify_postgres.py | 0 | 72 passed, five neural checks intentionally skipped. Isolated temporary DB, upgrade from 0001, synthetic price preservation, Alembic schema comparison and competing rental approvals. postgres-tests.txt and postgres-commands.json |
| SQLite upgrade | python scripts/verify_sqlite_upgrade.py | 0 | Existing legacy appointment survived migration, seed and RESTRICT check. sqlite-upgrade.log |
| Existing deterministic tasks | python evaluate.py tasks --output ../docs/v03 | 0 | 17 distinct scenarios passed. tasks.json |
| Rental task gate | python rental_eval.py | 0 | One connected scenario with 9 scored checks, 0 failures. Real local API and SQL, fixed clock, deterministic language handling. rental-eval.json |
| Failure gate | test_evaluator_gate | 0 | Child evaluator returned 1 for an impossible top-ranked ID and recorded one failed case. |
| Index isolation | test_eval_index_isolation | 0 | Evaluation ran in a subprocess and preserved the configured index directory and sentinel pointer byte-for-byte. |
| Retrieval | HF_HUB_OFFLINE=1 python evaluate.py retrieval --rerank --output ../docs/v03 | 0 | 27 unique queries × 4 configurations, 108 executions. Per-case returned IDs, dataset/model identities and timing in retrieval.json |
| Frontend | npm run build and npm run typecheck | 0 | Next.js production build and TypeScript passed. build.log and typecheck.log |
| Browser | CHROMIUM_PATH=/path/to/headless_shell HF_HUB_OFFLINE=1 python scripts/rental_browser.py | 0 | Actual browser passed search, ordered comparison, cited pickup, exact quote, pending status, individual staff approval and reload. browser.log and browser-commands.json |
| Secret patterns | python scripts/scan_secrets.py | 0 | See secret-scan.json for pattern scope and result. |
| Dependencies | npm audit --omit=dev --json and python -m pip_audit --no-deps --disable-pip -r requirements.lock --format json | 0 | Frontend zero findings. Python resolved baseline lock audited, CPU-specific PyTorch wheel unauditable. npm-audit.json and python-audit.json |
| Live generative inference | python rental_eval.py --live --out ../docs/v03/live.json | 0, skipped | No configured credentials/model. Zero real provider calls, unverified quality and unknown cost. |
| Pinecone | mock adapter contract and failure tests | — | No live Pinecone validation. All reported learned retrieval results used local FAISS. |
| Docker Compose | docker compose up --build -d | 127 | Docker CLI unavailable. On a Docker host follow docs/UPGRADE.md, create an employee via docker compose exec api python -m app.employee demo-reviewer reviewer, then use /rentals. Restart db/api/web and confirm the same rental record ID after reload. |
| Remote CI | .github/workflows/ci.yml | — | Configured only. No push or remote execution. |

An early build was killed during trace collection while other neural checks were running. A subsequent production build and browser run completed. The working Chromium executable was the installed headless shell. The runner can use a standard Playwright install on another machine.

## Retrieval comparison

| Strategy | Recall@3 | MRR | nDCG@3 | Citation valid | Expected passage support | Negative abstention | p50 ms | p95 ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| lexical | 0.896 | 0.840 | 0.844 | 1.000 | 0.593 | 0.667 | 12.384 | 21.777 |
| dense | 0.958 | 0.861 | 0.889 | 1.000 | 0.630 | 0.667 | 12.496 | 52.958 |
| hybrid | 1.000 | 0.875 | 0.903 | 1.000 | 0.630 | 0.667 | 12.263 | 55.699 |
| reranked | 1.000 | 0.931 | 0.948 | 1.000 | 0.630 | 0.667 | 504.202 | 2182.496 |

Twenty-four positive queries have document judgments. Three negative queries have no supported answer. Passage support requires the annotated supporting phrase in an accepted chunk from each required document. A negative case passes this check only when the system abstains. This stricter measure includes the similarity threshold and all required evidence, explaining the gap between retrieval recall and support. The score uses authored exact phrases and is a reproducible proxy for semantic support. The set includes a multi-document request and an unsupported refund question. Index lifecycle tests replace conflicting document versions and verify stale IDs disappear. The benchmark does not independently measure every possible version conflict or customer paraphrase.

Hybrid fusion ranks slightly better than dense on this dataset. Reranking improves MRR again at higher latency. All four strategies abstained on two of the three negative questions. Source/excerpt validity was 100%. The small evaluation cannot establish a general hallucination or abstention rate.

## Accounting and limitations

The end-to-end evaluator uses a fresh database and checks customer-facing values, the two vehicle IDs, dates and budget unit, quote cents, unchanged terms, pending review and committed reservation after reload. The four follow-ups are successive turns of one scenario. The other checks in the connected evaluation concern clarification and lifecycle outcomes. It would be misleading to count these as nine unique customer scenarios. Model responses are only used for typed follow-ups in live mode. Some expected lifecycle outcomes are encoded in the runner. Dataset files are shipped for reproducibility, but there is no external blinded holdout or timestamped preregistration. The new tests include a mocked rental planner contract. The browser test uses real local policy retrieval. Cost estimates remain null with no paid inference and no pricing schedule supplied.

1. **High, before deployment**. Live model/Pinecone execution, remote CI and Compose persistence remain unverified. Legacy staff endpoints still use the local shared secret. Individual reviewer and manager tokens protect the new rental workflow. Token issuance is a local operator command. Production identity lifecycle and revocation UI remain open.
2. **High, AI quality**. Weak or missing policy support remains visible in the table. The UI should escalate unresolved claims. Rental discovery supports a finite syntax and explicit date form. The optional live planner covers rental follow-ups, and the live evaluation has one connected scenario. Broader language coverage, calibrated support judgments and a larger independent holdout remain necessary.
3. **Medium, workflow**. Staff handles cancellation. Rental decisions check allowed transitions and approvals atomically. Exact customer quote submissions have payload-matched idempotency. A repeated staff decision returns a status conflict after the first success. Self-service token recovery, multi-device history, distributed throttling, payment, tax and deposit handling are outside this demo. Browser verification used the desktop viewport. A mobile-specific interaction run remains open.
4. **Medium, context and retention**. The UI restores rental state and SQL ledger on reload. Follow-up comparison text and policy excerpts are transient in the rental panel. The rental ledger persists through clearing chat. An operational retention schedule remains open.

## Reviewer challenges

Run tests/test_rental.py on PostgreSQL. In particular, check that two different customers can submit inquiries for the same slot but only one approval creates occupied dates. Try altering the quote total before submission. Approve an adjacent reservation, attempt an overlapping extension, and verify the original record and occupied dates survive. Change a vehicle rate before acceptance and verify the accepted unexpired quote snapshot. Change the displayed search order and attempt an old turn reference. Verify manager-only fleet updates reject a reviewer token. Inspect rental-eval.json and retrieval.json before quoting quality metrics.

## Interview and résumé evidence

- Built a SQL-backed rental workflow with calendar-month quotes, exact customer acceptance and staff-reviewed reservations. Source: backend/app/rentals.py and migration 0004. Evidence: test_flagship, test_expiry_rate_change_and_exact_terms and browser.log.
- Enforced exclusive vehicle occupancy across concurrent approvals and atomic reservation extensions using a composite vehicle/date key. Source: RentalDay and the staff decision transaction. Evidence: PostgreSQL test_competing and test_flagship.
- Evaluated learned retrieval across 27 synthetic policy questions and four ranking configurations, reporting citation support, abstention and latency alongside retrieval quality. Source: backend/app/rag.py and backend/evaluate.py. Evidence: docs/v03/retrieval.json.
