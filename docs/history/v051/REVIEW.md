# Easy Route Auto AI v0.5.1 | Engineering verification

Independent portfolio implementation by Taksh Pathak. All fleet, prices, policies, and operational records are synthetic. The starting v0.5.0 archive matched SHA-256 `2968c2f179a0ef2081e1e4af80f51571e3c095682353e55ee22cd2f3ac00f753` and all 286 entries in its manifest. Qualification used source unpacked into an empty directory. Subsequent corrections were extracted from the revised candidate and affected checks rerun.

## Review findings

| Finding | Application change | Evidence |
|---|---|---|
| A planner raised a saved $950 cap while adding seats | rentals.interpret resolves fully understood edits to the fields explicitly requested. edit_query protects retained budget and period, checks amounts, and asks for clarification on an unsupported change. | An HTTP test injects $1,200 via a mocked provider. The response and restored query stay at $950 with seven seats and no eligible SUVs. An explicit raise to $1,200 returns vehicle 5, the $1,040/month Kia Sorento. A historical price mention also leaves the query intact. |
| Upper seat bounds became minimums | rental_language.check_comparators detects upper and exclusive seat bounds before extracting the number. offline applies supported inclusive minimums. | The API asks for clarification for “under seven” and “maximum of five”. With $1,200, inclusive seven returns ID 5 and inclusive eight returns no vehicles. The browser reload verifies the cap and seat count. |
| The wrong policy answered reservation expiry | rental_evidence.assess scopes the fifteen-minute rule to quotes. Reservation expiry requests ask which reservation to review. A competing booking is distinguished from third-party pickup permission. | HTTP response plus citation assertions, local neural held-out cases and browser checks cover all three questions. A conflict cites “The original reservation stays active if the extension conflicts.” |
| Mode comparison and release gates | rental_eval scores restored query, visible vehicle constraints, record counts, task outcomes, provider events and tokens. CI runs the frozen cases. | heldout.json and live.json share the same dataset checksum. A mocked 503 is separately identified in fault.json. |

Before editing the application, seven focused HTTP cases produced five failures and two passes, including a correct quote TTL control. The policy reproduction supplied actual corpus sentences to isolate answer selection from retrieval. An additional exploratory price-mention test exposed a sixth failure during development. See before.log and additional-before.log. The completed browser and held-out checks use the actual SQL and neural retrieval paths.

## Release checks

| Feature | Mode | Result | Scope |
|---|---|---|---|
| Backend, SQLite | Real SQL and local neural models | 115 passed, zero failed or skipped | Includes ownership, transactional conflicts and extension rollback |
| Backend, PostgreSQL | Disposable local PostgreSQL | 110 passed, 5 skipped, zero failed | Five opt-in neural cases run on SQLite |
| Upgrade | Both databases | Passed | Legacy records retained, Alembic schema checks passed |
| Task evaluations | Deterministic and SQL | 17/17 legacy, 14/14 rental, 10/10 prior comparison, 5/5 patch scenarios | Dataset-specific, plus grammar smoke checks |
| Next.js | Production build and TypeScript | Passed | Local installation from the lockfile |
| Browser | Running Next.js, FastAPI, SQLite, learned retrieval | Passed | Desktop and mobile rental flow plus legacy customer workflow |
| Provider fault | Injected HTTP 503 | Passed | One attempted call, zero completed calls |
| Live LLM | Unexecuted | Zero attempted calls | Authorized key/model pair unavailable |
| Compose restart | Blocked | Exit 1 | No Docker executable or daemon socket |
| Basic secret scan and dependency audits | Local scanner, pip-audit, npm audit | No findings in the scanned inputs | Pattern and known-advisory checks only |

## Frozen multi-turn results

The five authored scenarios were frozen before tuning (freeze.sha256). Each starts with an independent seeded search followed by two assistant turns. Some probes restate reviewer examples. These are targeted regressions, not a population estimate. All 15 steps passed. Across the ten assistant turns p50 was 16.4 ms and p95 was 26.9 ms, measured in-process and excluding model loading.

| Scenario | Steps passed | Customer-visible and persisted outcome |
|---|---:|---|

| unchanged-ceiling | 3/3 | No match at the retained cap, then a seven-seater after the explicit raise. |
| exclusive-seat-limit | 3/3 | Exclusive upper limit asks for a minimum, then two five-seat SUVs meet the inclusive minimum. |
| inclusive-seat-limit | 3/3 | Maximum asks for clarification, then a six-seat minimum at $950 returns no match. |
| expiry-subject | 3/3 | Quote expiry cites fifteen minutes. Reservation expiry returns a clarification with zero citations. |
| extension-conflict | 3/3 | Extension conflict cites the original reservation protection. Declining a quote creates no record. |

The evaluator checked 15 restored queries, 19 ordered-ID expectations and 13 returned vehicle rows. Zero vehicle constraint violations, silent relaxations or unintended quote rows were observed. Selection remained empty and occupancy remained zero at each of the 15 checkpoints. Deterministic mode used zero provider calls and zero tokens. Live quality, token usage, latency and cost remain unmeasured. Per-step HTTP results, SQL observations, event counts and elapsed times are in heldout.json.

## Retrieval and answer support

Each configuration ran the same 32 original questions and eight fact-level questions with local pinned model weights. Recall and MRR measure retrieval. Support checks the returned excerpts and required staff escalations. The following counts refer to the eight fact-level questions.

| Configuration | Recall@3 | MRR | Correct answers | Valid / emitted citations | False accepts | p50 / p95 ms |
|---|---:|---:|---:|---:|---:|---:|

| lexical | 0.875 | 0.688 | 7/8 | 4/4 | 0 | 9.7 / 12.3 |
| dense | 1.000 | 1.000 | 8/8 | 5/5 | 0 | 9.6 / 10.7 |
| hybrid | 1.000 | 0.938 | 8/8 | 5/5 | 0 | 10.2 / 12.4 |
| reranked | 1.000 | 1.000 | 8/8 | 5/5 | 0 | 81.6 / 117.5 |

Dense and reranked retrieval both answered all eight correctly. Reranking cost additional latency. Lexical retrieval missed f6. On the original 32, accepted-answer support was 24/32 lexical, 25/32 dense, 24/32 hybrid and 25/32 reranked. All ten original rental cases passed support scoring in each configuration. The remaining misses are in the legacy dealership questions. retrieval.json includes every case, rubric and corpus hashes, model revisions and separate rental/legacy metrics.

## Reproduce

Follow README.md to install the application. Activate the Python environment, install pgserver and pip-audit for diagnostics, and unset DATABASE_URL. Cache the two pinned Hugging Face revisions before offline checks. The local run used HF_HUB_OFFLINE=1, OMP_NUM_THREADS=1, MKL_NUM_THREADS=1 and TOKENIZERS_PARALLELISM=false. Set EASY_EVIDENCE_DIR to the absolute docs/v051 directory. Install the browser with cd frontend && npx playwright install chromium --only-shell. For live scoring set OPENAI_API_KEY and OPENAI_MODEL outside the repository, then run the live command below. A zero exit with status unexecuted is a recorded skip. On a Docker host leave ports 3000 and 8000 free for the Compose probe.

| Check | Command from repository root | Exit |
|---|---|---:|

| postgres | `python scripts/verify_postgres.py` | 0 |
| upgrade | `python scripts/verify_sqlite_upgrade.py` | 0 |
| frontend | `cd frontend && npm ci --no-audit && npm run build && npm run typecheck` | 0 |
| compose | `python scripts/verify_compose.py` | 1 |
| live | `cd backend && python rental_eval.py --live --dataset evaluation/holdout_v051.json --out ../docs/v051/live.json` | 0 |
| legacy | `cd backend && python evaluate.py tasks --output ../docs/v051` | 0 |
| secrets | `python scripts/scan_secrets.py` | 0 |
| sqlite | `cd backend && EASY_RUN_NEURAL=1 python -m pytest -q --junitxml=../docs/v051/sqlite.xml` | 0 |
| retrieval | `cd backend && python evaluate.py retrieval --rerank --output ../docs/v051` | 0 |
| heldout | `cd backend && python rental_eval.py --dataset evaluation/holdout_v051.json --out ../docs/v051/heldout.json` | 0 |
| rental | `cd backend && python rental_eval.py --out ../docs/v051/rental.json` | 0 |
| compare | `cd backend && python rental_eval.py --dataset evaluation/rental_comparison_v5.json --out ../docs/v051/comparison.json` | 0 |
| browser | `REQUEST_LIMIT_PER_MINUTE=300 CHROMIUM_PATH=$HOME/.cache/ms-playwright/chromium_headless_shell-1194/chrome-linux/headless_shell python scripts/rental_browser.py` | 0 |
| fault | `cd backend && python rental_eval.py --provider-fault --dataset evaluation/rental_fault_v5.json --out ../docs/v051/fault.json` | 0 |
| python_audit | `pip-audit --disable-pip --no-deps -r backend/requirements.lock -f json -o docs/v051/python-audit.json` | 0 |
| audit | `cd frontend && npm audit --omit=dev --json >../docs/v051/npm-audit.json` | 0 |
| legacy_browser | `EASY_EVIDENCE_DIR=$PWD/docs/v051/legacy-browser REQUEST_LIMIT_PER_MINUTE=300 CHROMIUM_PATH=$HOME/.cache/ms-playwright/chromium_headless_shell-1194/chrome-linux/headless_shell python scripts/browser_e2e.py` | 0 |
| smoke | `cd backend && python benchmark.py` | 0 |

For the pre-fix HTTP reproduction the command was `cd backend && python -m pytest -q tests/test_patch51.py` (exit 1). The initial focused rerun including test_v05.py passed 28 tests. The additional price-mention and seat-boundary pair returned exit 1 before the final guard. The final database suites include all nine patch tests. The host Chromium initially failed to create its process socket, so the successful browser runs used Playwright’s pinned headless shell. The legacy browser initially used 127.0.0.1 as the page origin while CORS authorized localhost. Its test now opens the same origin as the documented application. No CORS policy was broadened.

## Remaining verification and limitations

1. **High for a live-model demo.** No authorized provider credentials were available. Run the scored live command on the frozen cases before making generative performance claims.
2. **High for deployment.** Compose restart persistence and hosted CI have no observed pass for this release. On a Docker host run the recorded Compose command, which checks the original reservation ID and occupied dates following restart. Local SQL and browser checks cover application behavior.
3. **Moderate for unrestricted questions.** The seat field is a minimum. Upper limits trigger clarification. Personal reservation expiry asks for the specific reservation. The synthetic fact catalog deliberately escalates unfamiliar requests. Live Pinecone service execution is unverified.
4. **Low for interpreting benchmarks.** Small authored fixtures and in-process timings have limited external validity. Legacy document answer support varies across retrieval strategies.

## Reviewer handoff

Start with backend/tests/test_patch51.py and backend/evaluation/holdout_v051.json. Compare the SQL-backed state before and after the hostile planner response. In the rental browser, compare quote-expiry and reservation-expiry replies and check their cited text. Use README.md for the complete customer-to-staff demonstration. Changed files are listed in changes.json. Source and evidence digests are in SHA256SUMS. All measurements describe this independent synthetic implementation.
