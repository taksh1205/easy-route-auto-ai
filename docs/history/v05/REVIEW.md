# Easy Route Auto AI v0.5.0 — reviewer handoff

Independent synthetic portfolio implementation by Taksh Pathak. Starting archive SHA-256 `a6f0ae2f36758e305cd82f0ed0611d2225a983f1262dcfe33a01760e1e00d5f8`. Verification ran against source unpacked into an empty directory. Original data, terms, migrations and operational approvals remain compatible. The README contains the short interview walkthrough.

## Findings and regression coverage

| Finding | Fix | Verification |
|---|---|---|
| Declined and deferred commands created quotes | rental_language.authorized_reference matches a whole affirmative instruction. rentals.interpret checks the proposed action and vehicle against that instruction even in model mode. | reproduction.jsonl records v0.4 HTTP 200 and unintended writes. test_v05.py checks HTTP response, selected ID, row count and statuses. |
| Comparing cars selected the second one | rentals.reference updates selection only on explicit select. rentals.ask uses that selection and rechecks eligibility. rentals() invalidates ambiguous v0.4 selections. | Fresh selection, prior selection, seat inspection, invalid ordinals and stale legacy selection are tested. |
| A price floor became a ceiling | Plan adds a typed comparator. check_comparators and edit_query reject unsupported floors and ranges before saving. | The full canonical query and returned SQL IDs are asserted for seven seats, a cap, a floor, a range and a one-field edit. |
| A relevant passage implied support for undocumented details | rental_evidence.assess checks simple clauses against a bounded fact catalog and extracts actual sentences from retrieved chunks. policy_reply and the rental page display both citations and unresolved details. | An exact pickup time goes to staff. The compound extension-and-rate case now cites both policies. |
| Planner calls were estimated from turn count | rental_planner.capture_calls observes attempts, completed responses, validated plans, failures, returned usage and elapsed time. rental_eval scores API output and database effects. | The stale request recorded zero attempts. An injected HTTP 503 recorded one attempt, one error, zero validated plans and zero quote rows. |

## Application results

The new deterministic comparison passed 10/10 scenarios over 22 steps. This included 12 ordinary assistant turns. The stale-turn preflight is scored separately. The five zero-quote checks produced 0 unintended quote rows. Dataset hashes are in frozen.sha256. These authored scenarios measure the listed behaviors and do not establish accuracy on arbitrary customer language.

| Scored expectation | Correct | Total |
|---|---:|---:|
| operation | 11 | 11 |
| arguments | 10 | 10 |
| constraints | 13 | 13 |
| record_count | 6 | 6 |

The live-model result is unexecuted. The environment had no authorized model/key pair. No generative quality, cost or relative winner was inferred. Actual embedding and cross-encoder executions used the local CPU. Mocked provider tests are identified separately. With a configured model the evaluator stores available token usage. Optional RENTAL_INPUT_USD_PER_M and RENTAL_OUTPUT_USD_PER_M specify USD per million tokens for cost estimation.

## Retrieval results

The inherited 32 questions and eight new fact-level questions ran across four configurations, giving 160 ranked runs. On the original set, relevance and expected phrases use the prior document judgments. On the new set, answer support separately checks source IDs, required excerpts and the specific staff escalation. Five of eight questions require staff confirmation of at least one detail.

| New questions | Recall@3 | MRR | Supported outcomes | False accepts | Valid / emitted citations | p50 / p95 ms |
|---|---:|---:|---:|---:|---:|---:|
| lexical | 0.875 | 0.688 | 6/8 | 0 | 3/3 | 23.0 / 45.1 |
| dense | 1.000 | 1.000 | 7/8 | 0 | 4/4 | 24.1 / 32.1 |
| hybrid | 1.000 | 0.938 | 7/8 | 0 | 4/4 | 17.6 / 86.3 |
| reranked | 1.000 | 1.000 | 7/8 | 0 | 4/4 | 146.2 / 221.8 |

| Original questions | Recall@3 | MRR | Supported outcomes | False accepts on negatives | Valid candidate lists | p50 / p95 ms |
|---|---:|---:|---:|---:|---:|---:|
| lexical | 0.926 | 0.840 | 24/32 | 0/5 | 32/32 | 30.8 / 49.9 |
| dense | 0.963 | 0.877 | 25/32 | 0/5 | 32/32 | 21.5 / 36.1 |
| hybrid | 0.963 | 0.858 | 24/32 | 0/5 | 32/32 | 19.1 / 45.1 |
| reranked | 1.000 | 0.938 | 25/32 | 0/5 | 32/32 | 341.5 / 814.7 |

On r26, both the extension-review sentence and the daily-rate sentence now reach the customer. The old dense threshold had rejected both. Reranking added latency without improving support over dense or hybrid on the fresh set. BM25 shares query encoding with the other retrieval paths. These are single-host timings, not production latency guarantees.

**Fresh-case failures retained**

- lexical, f6: How long does a quote last? Returned 0 excerpts. Escalated how long does a quote last.
- lexical, f7: What if extra nights conflict with someone else's booking? Returned 0 excerpts. Escalated the requested permission or exception.
- dense, f7: What if extra nights conflict with someone else's booking? Returned 0 excerpts. Escalated the requested permission or exception.
- hybrid, f7: What if extra nights conflict with someone else's booking? Returned 0 excerpts. Escalated the requested permission or exception.
- reranked, f7: What if extra nights conflict with someone else's booking? Returned 0 excerpts. Escalated the requested permission or exception.

## Reproduction commands and exit codes

Use the activated Python environment from README and unset DATABASE_URL for tests. HF_HUB_OFFLINE=1 was set after caching the pinned model files. Commands run from repository root unless prefixed with cd. Inspect the corresponding .log and .exit files for the full results.

| Check | Exact command | Exit | Outcome |
|---|---|---:|---|
| sqlite | `cd backend && EASY_RUN_NEURAL=1 python -m pytest -q --junitxml=../docs/v05/sqlite.xml` | 0 | 106 passed, 4 warnings in 43.49s |
| postgres | `python scripts/verify_postgres.py` | 0 | 101 passed, 5 skipped, 1 warning in 24.17s |
| upgrade | `python scripts/verify_sqlite_upgrade.py` | 0 | Migration, seed preservation and schema check |
| legacy | `cd backend && python evaluate.py tasks --output ../docs/v05` | 0 | 17/17 scenarios |
| rental | `cd backend && python rental_eval.py` | 0 | 14/14 inherited rental scenarios |
| comparison | `cd backend && python rental_eval.py --dataset evaluation/rental_comparison_v5.json --out ../docs/v05/comparison.json` | 0 | 10/10 deterministic scenarios |
| live | `cd backend && python rental_eval.py --live --dataset evaluation/rental_comparison_v5.json --out ../docs/v05/live.json` | 0 | Unexecuted. Set OPENAI_API_KEY and OPENAI_MODEL to perform the scored live run. |
| fault | `cd backend && python rental_eval.py --provider-fault --dataset evaluation/rental_fault_v5.json --out ../docs/v05/fault.json` | 0 | Mocked 503; one passing scenario |
| retrieval | `cd backend && python evaluate.py retrieval --rerank --output ../docs/v05` | 0 | Local neural inference; per-case results and model revisions in retrieval.json |
| frontend | `cd frontend && npm ci --no-audit && npm run build && npm run typecheck` | 0 | Production build and type checks |
| browser | `REQUEST_LIMIT_PER_MINUTE=300 CHROMIUM_PATH=$HOME/.cache/ms-playwright/chromium_headless_shell-1194/chrome-linux/headless_shell python scripts/rental_browser.py` | 0 | Desktop and mobile Chromium, real API, SQLite and policy retrieval |
| compose | `python scripts/verify_compose.py` | 1 | Blocked: Docker CLI unavailable. Run on a Docker host with free ports 3000 and 8000. |
| secret | `python scripts/scan_secrets.py` | 0 | Basic credential pattern scan |

The PostgreSQL suite skips five optional neural checks that ran under SQLite. A first accelerated browser run using the default 90 requests/minute triggered HTTP 429 during staff queue refresh after a committed approval. The repeat uses a disposable quota of 300 because two browser customers and a staff actor share one loopback address. The shipping API default remains 90. There is no hosted CI run URL for this source ZIP. No Git remote was configured and publication was not authorized.

## Changed files


- `.github/workflows/ci.yml`
- `README.md`
- `backend/app/main.py`
- `backend/app/rag.py`
- `backend/app/rental_evidence.py`
- `backend/app/rental_language.py`
- `backend/app/rental_planner.py`
- `backend/app/rentals.py`
- `backend/evaluate.py`
- `backend/evaluation/policy_facets_v5.json`
- `backend/evaluation/policy_support_rubric_v5.json`
- `backend/evaluation/rental_comparison_v5.json`
- `backend/evaluation/rental_fault_v5.json`
- `backend/rental_eval.py`
- `backend/tests/test_v05.py`
- `frontend/app/rentals/page.tsx`
- `frontend/package-lock.json`
- `frontend/package.json`
- `frontend/tests/rental.cjs`
- `scripts/browser_e2e.py`
- `scripts/rental_browser.py`
- `scripts/verify_postgres.py`
- `scripts/verify_release.py`
- `scripts/verify_sqlite_upgrade.py`

docs/v05 contains the new evidence, including raw per-case results and the source checksum manifest.

**Reviewer handoff.** Try the README walkthrough, then vary an ordinal or a price comparator. Inspect the quote ledger after each declined turn. For policy questions compare the excerpt with the exact detail requested. The bounded language grammar, the missed conflict paraphrase, live generative quality and container restart verification are the remaining interview and deployment limits.
