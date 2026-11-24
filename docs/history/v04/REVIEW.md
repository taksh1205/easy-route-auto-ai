# Easy Route Auto AI v0.4.0 — engineering and verification

Taksh Pathak’s independent synthetic portfolio application. Run the interview demo in the root README. The downloadable source descends from the reviewed v0.3.0 archive with SHA-256 `f921697dee60c9a9e55019ea1827be50c7d0f940b29ac0c14e21b0db6059b8a2`. All entries in its source manifest matched before editing. The fresh pre-change SQLite run passed 72 tests with five optional tests skipped. Historical evidence remains under docs/v02 and docs/v03.

## Findings, changes and evidence

| Reviewer finding | Implemented behavior | Check and result |
|---|---|---|
| Seat requirements disappeared during discovery | Query.min_seats flows from the form and typed language patch into SQL, serialized results and restored context. Unrecognized modifiers in offline discovery prompt clarification. | seven-seat-no-match and seven-seat-qualifier checked empty results at $950 and vehicle 5 at $1,100. |
| Budget edits changed the trip | Edit patches carry independent cents, period, body, dates, seat count and calendar-month intent. The server validates the merged query. | replace-budget retained April 1–8 and monthly billing. independent-field-edits actually changed sedan to SUV and seven days to one calendar month. The evaluator compared whole queries and restored SQL-backed state. |
| Quotes silently used the second result | Explicit positions use session-owned turn IDs. A selected reference requires a current selected ID. Every referenced vehicle must still qualify in SQL. | reordered-selection changed the fleet price order and selected ID 7 first. Unselected and out-of-range requests wrote zero quotes. Browser selected ID 6 and quoted it. |
| One disabled car erased the display | Restoration preserves surviving IDs in their previous order and replaces the turn ID when the list shrinks. | stale-display retained ID 7 after disabling ID 6. The old turn returned 409 with zero quotes. |
| Policy questions produced selection prompts or misleading success messages | Original question goes to a rental-scoped index. The UI renders server-returned excerpts and chunk IDs or an explicit staff escalation. Rental-specific evidence checks apply before rendering. | cancellation-excerpt checked the supporting words and source. unsupported-policy checked empty citations and visible escalation. |
| UTC rollover and retroactive extensions | Discovery, search, quote eligibility and approval use the Phoenix business date. Extension creation and staff approval each check the original return boundary. | phoenix-evening approved same-day pickup after UTC midnight. Five parametrized boundary tests and extension-cutoff checked rejection, original confirmation and preserved occupied dates. |
| Weak acceptance gate | Each scenario starts with newly seeded SQL. Program checks HTTP status, visible values and stored effects. A deliberate bad budget in a subprocess must produce exit 1. | 14 scenarios, 48 steps, 17 assistant turns, zero final failures. First run is preserved. One fix added routing for indirect questions. Another corrected the evaluator's session creation date to avoid artificial expiry. |
| Limited browser coverage and stale artifacts | Desktop and 390×844 mobile Chromium sessions exercise discovery, changes, selection, policy, quotes and a competing request. Staff approves, extends, reloads, clears chat and cancels. CI uploads a fresh run directory after checks with always(). | Browser completed locally. Build, TypeScript and both database migration checks passed. Hosted CI execution remains unverified. |

## Executed checks

Working directories are relative to repository root. For local offline neural runs, HF_HUB_OFFLINE=1 used an existing cache of pinned models. The first installation needs the downloads described in the README. No live generative inference was performed.

| Directory | Command | Exit | Actual evidence |
|---|---|---:|---|
| backend | EASY_RUN_NEURAL=1 HF_HUB_OFFLINE=1 python -m pytest -q --junitxml=../docs/v04/tests.xml | 0 | 85 passed, zero failures or skips. Includes real embedding, reranker and isolated index runs. See tests.log and tests.xml. |
| root | HF_HUB_OFFLINE=1 python scripts/verify_postgres.py | 0 | 80 passed, five optional tests skipped. Temporary cluster verified upgrade, reseed preservation and Alembic check. See postgres-tests.txt and postgres-commands.json. |
| root | python scripts/verify_sqlite_upgrade.py | 0 | Migration chain, preserved legacy records, reseed and schema check. See sqlite-upgrade-commands.json. |
| backend | HF_HUB_OFFLINE=1 python rental_eval.py | 0 | rental-eval.json contains final per-step expectations, responses, database observations and timings. scored.log is the final console log. |
| backend | python evaluate.py tasks --output ../docs/v04 | 0 | All 17 legacy scenarios passed. See tasks.json. |
| backend | python benchmark.py | 0 | Legacy grammar smoke check. See smoke.log. |
| backend | HF_HUB_OFFLINE=1 python calibrate_policy.py ../docs/v04/calibration-final.json | 0 | Six development questions with document labels, candidate scores and threshold sweep. |
| backend | HF_HUB_OFFLINE=1 python evaluate.py retrieval --rerank --output ../docs/v04 | 0 | 32 unique questions × four ranking strategies. See retrieval.json and retrieval-final.log. |
| frontend | npm run build and npm run typecheck | 0 each | build.log and typecheck.log. |
| root | HF_HUB_OFFLINE=1 CHROMIUM_PATH=$HOME/.cache/ms-playwright/chromium_headless_shell-1194/chrome-linux/headless_shell python scripts/rental_browser.py | 0 | Real Next.js, HTTP, disposable SQLite, local neural retrieval and Chromium. browser-commands.json and browser-e2e.txt. Omit CHROMIUM_PATH when using Playwright's installed default. |
| root | python scripts/scan_secrets.py | 0 | Basic credential-pattern scan, secret-scan.log. |
| frontend | npm audit --omit=dev --fetch-retries=0 --json | 0 | Zero reported vulnerabilities, npm-audit.log. |
| root | PYTHONPATH=/tmp/era04-audit python -m pip_audit --no-deps --disable-pip -r backend/requirements.lock --format json | 0 | Zero advisories reported for auditable packages, CPU-specific torch wheel skipped. Scanner installed separately for this run. |
| backend | python rental_eval.py --live --out ../docs/v04/live.json | 0, unexecuted | Missing provider credentials/model. Set OPENAI_API_KEY and OPENAI_MODEL, unset DATABASE_URL, run this command to score live responses. Schema and dispatch were tested using a mocked HTTP provider. |
| root | docker compose version | 127 | Docker executable unavailable. The persistence runner also exited 1 with an explicit missing-CLI message (compose.log). Run python scripts/verify_compose.py on a Docker host with free ports 3000 and 8000. It creates a dedicated Compose project and compares the approved record and occupied dates across restart. |

## Retrieval measurements

The acceptance rule uses document scope and dense similarity. Development calibration minimized document classification errors across a grid of thresholds, breaking ties conservatively. The original threshold of 0.35 rejected the relevant billing candidate at 0.29 and both extension-plus-rate candidates at about 0.22. We clarified the synthetic passages, added a document-procedure source, and froze a rental cutoff of 0.31 based on six development questions. The rental evaluation includes five previously published questions and five additional authored questions. These are small project fixtures, not an independent natural-language traffic sample.

| Ranking | Rental Recall@3 / MRR / nDCG@3 | Rental supported positives | False accepts on three negatives | Rental median / p95 milliseconds | Legacy MRR |
|---|---|---:|---:|---|---:|
| BM25 | 1.00 / 1.00 / 0.989 | 6/7 | 0 | 13.3 / 18.1 | 0.783 |
| Dense | 1.00 / 1.00 / 1.00 | 6/7 | 0 | 10.7 / 15.6 | 0.833 |
| Hybrid | 1.00 / 1.00 / 1.00 | 6/7 | 0 | 10.1 / 12.2 | 0.808 |
| Hybrid plus cross-encoder | 1.00 / 1.00 / 1.00 | 6/7 | 0 | 106.5 / 133.8 | 0.917 |

Each rental strategy produced valid citation identities for all ten questions. Validity checks chunk identity and stored text. Support separately checks required document IDs and phrases. The lexical variant still computes dense scores for evidence acceptance. Rental timings therefore compare the full retrieval paths. Legacy results cover 22 separate questions and have their own summaries in retrieval.json.

Reranking improved legacy MRR but added about 96 ms to median rental latency without increasing rental support. The partial-month answer now passes with dense score 0.366. On the compound extension-plus-rate question the reranker found both required documents, but their dense scores of 0.275 and 0.259 fell below the cutoff. The assistant escalated. The browser also revealed a pickup paraphrase that can lead to abstention; the browser requires either evidence or escalation for that paraphrase and separately requires a real pickup citation. The initial failed browser assertion is retained.

## Remaining issues by severity

1. **High for open-ended interview claims.** Live LLM task quality has no measured result. The demonstrated language mode is a finite offline grammar with real SQL and local neural policy retrieval. Broader free-form reference and constraint extraction need blinded live-model evaluation. Three negative policy questions give little assurance about false acceptance outside this dataset.
2. **High for deployment.** Docker startup and persistence across restart await an actual Docker host. The application targets a local demonstration. The legacy employee explorer still has shared-token access. Rental operations use individual role-checked staff identities. Pinecone has contract coverage only.
3. **Medium for policy coverage.** Multi-topic evidence acceptance misses one supported rental question; retain abstention until query decomposition or alternative confidence calibration improves independent measurements. Legacy answer support ranged from 60% to 65% on positive queries.
4. **Medium for supply-chain evidence.** The Python advisory scan could not audit the CPU-specific torch wheel. Pattern scans have limited coverage.

## Resume bullets for the independent portfolio project

- Built a FastAPI rental assistant that enforces seat and budget constraints in SQL and resolves conversational references against session-owned results. Evidence in app/rentals.py and the 14-scenario rental evaluation.
- Evaluated BM25, MiniLM embeddings, hybrid retrieval and cross-encoder reranking on 32 policy questions, measuring citation support, abstention and latency. Evidence in app/rag.py, evaluate.py and retrieval.json.
- Implemented PostgreSQL-backed reservation approval and atomic extensions, verified with concurrent approval tests and a desktop/mobile Chromium workflow. Evidence in app/rentals.py, tests/test_rental.py and frontend/tests/rental.cjs.

## Reviewer handoff

Run the short README demo, change a non-default budget and reorder rates before selecting a car. Inspect case r26 in retrieval.json alongside the corpus and calibration data. Exercise the stale-turn and exact-boundary extension tests on PostgreSQL. For new claims about generative performance or container persistence, require a scored live run or completed Compose persistence log respectively.
