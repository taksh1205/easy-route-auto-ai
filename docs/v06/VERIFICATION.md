# v0.6.0 verification report

Source: Easy Route Auto AI v0.5.1 review ZIP (SHA-256 `8f66b90a…3bea02`, checksum verified on
receipt), upgraded in place. Every reviewer finding below was **reproduced through the HTTP API
before it was changed**. All results come from one final run of `scripts/verify_release.py` on
the finished code, with per-gate logs in [`evidence/`](evidence) and per-case outputs in
[`evaluations/`](evaluations).

Environment: Linux x86-64, CPU only, Python 3.13, Node 22, PostgreSQL 16 (tests and the upgrade
path), PostgreSQL 17 (Compose), Docker 29, Chromium (Playwright).

## Reviewer findings → fix → test

| # | Finding (v0.5.1 review) | Reproduced on v0.5.1 | Fix | Regression evidence |
|---|---|---|---|---|
| 1 | A first message whose planner output omits `min_seats` saves no seat requirement | "seven-seat SUV … under $950 monthly" plus an injected plan without seats saved `min_seats=None` and returned five-seat vehicles 6 and 7 | One reconciliation path for discovery **and** edits (`app/rental_constraints.py`). Explicit evidence overrides omitted or contradicting fields, ungrounded planner values trigger clarification, and overrides are returned to the client | `tests/test_v06_constraints.py`: omitted-seat, contradicted-values, ambiguous-quantity, ungrounded-value, valid-plan and free-form paraphrase cases, each checked against SQL rows and an independent read of the saved session. `release_v06` r01 and r07 |
| 2 | "Under $875" includes $875 | "under $875 monthly" returned vehicle 6 at exactly $875.00 | Strict bounds are canonicalized to the exact integer-cent ceiling `X − 1¢`. "At most" stays inclusive. "Can't go over" and "no more than" are ceilings, and floors and ranges clarify | `test_price_boundaries`: rates of $874.99, $875.00 and $875.01 × {under, at most} × {offline, mocked live}. Strict bound persists across turns. Legacy inclusive searches are unchanged |
| 3 | No genuine live-model comparison | — | Anthropic adapter added beside OpenAI behind one instrumented contract. Frozen `release_v06` set committed before any run | **Executed once** with `gpt-5.4-mini-2026-03-17` on the frozen set: 8/11 scenarios (offline 5/11), 0 unsafe outcomes, 16/16 validated calls (`eval-release-v06-live.json`) |
| 4 | Browser suites collide on port 3000 | Reproduced: `npm start` forks `next-server`, which survives termination | Shared harness with process groups, group kill with escalation, and a wait for port release | Rental and legacy suites passed back to back twice before release, then again in the final run, plus the new flagship suite |
| 4b | Compose restart persistence was never verified | Found a **new defect**: the `index` service fails with `PermissionError`, because the `modelcache` volume is created root-owned | The image creates `/home/app/.cache` owned by `app` | `compose-persistence.log`: fresh build → approve reservation → restart db/api/web → same record ID, status and occupied dates |
| 5 | README and interview packaging | — | Results table, three-minute demo, measured dense-vs-reranker tradeoff, architecture document, upgrade notes | `browser-flagship.log` runs the README demo verbatim |

Defects found and fixed during this release (not in the review):

- **Search form showed a stale budget** after a chat edit. Found from a screenshot; the flagship
  test now asserts the form values.
- **The lint autofix removed a side-effect import** in `alembic/env.py`, which left
  `alembic check` with empty metadata. The PostgreSQL migration gate caught it.
  `tests/test_migrations.py` now fails without the import.
- **Evaluation metric.** "Silent relaxation" counted turns that clarified (and saved nothing or
  kept the last accepted search). A relaxation is now silent only when the customer was not
  told. Two tests pin the definition.
- **Script portability.** Migration checkers called a bare `python`; they now use the active
  interpreter.

## Release gates (final run)

| Gate | Status | Seconds | Note |
|---|---|---|---|
| lint | passed | 0.0 |  |
| format | passed | 0.0 |  |
| backend-neural | passed | 27.9 |  |
| backend-postgres | passed | 18.2 |  |
| migrations-sqlite | passed | 2.1 |  |
| migrations-postgres | passed |  | run as non-root user postgres (initdb refuses root) |
| eval-legacy-tasks | passed | 0.7 |  |
| eval-rental-holdout | passed | 5.7 |  |
| eval-comparison-v5 | passed | 5.9 |  |
| eval-heldout-v051 | passed | 5.9 |  |
| eval-release-v06 | passed | 6.5 |  |
| eval-provider-fault | passed | 0.9 |  |
| eval-release-v06-live | passed | 0.1 | gpt-5.4-mini-2026-03-17; run once on the frozen set (safety gate) |
| eval-retrieval-4way | passed | 10.3 |  |
| frontend-typecheck | passed | 0.9 |  |
| frontend-build | passed | 10.7 |  |
| browser-rental | passed | 44.2 |  |
| browser-legacy | passed | 42.0 |  |
| browser-flagship | passed | 37.2 |  |
| secret-scan | passed | 0.4 |  |
| audit-npm | passed | 0.4 |  |
| audit-python | passed | 2.0 |  |
| compose-persistence | passed | 114.5 |  |

The PostgreSQL migration gate was run as the non-root `postgres` user, because `initdb`
refuses root. The runner records this gate as *blocked* when it is run as root. In the sandbox,
the Compose gate used a local override file (proxy and CA only), passed through
`EASY_COMPOSE_FILES`. The repository's `compose.yaml` and Dockerfiles are what was built.

## Frozen release set: offline grammar baseline

`backend/evaluation/release_v06.json` (SHA-256 `878cd234…510d55`, 11 scenarios, 28 steps) was
committed before any run. It is scored with `--gate safety`: task success is reported, and the
run fails only on an unsafe outcome.

**Offline: 5/11 scenarios, 15/28 steps. Safety: 0 unintended ledger rows across 24 write-safety
checks, 0 silent relaxations, 0 constraint-violating vehicles.**

| Scenario | Covers | Offline result | What happened on the failing step |
|---|---|---|---|
| r01-first-message-seven-seats | first-message discovery, hard constraint, honest no-match, explicit relaxation | fail (safe) | “Looking for an SUV that seats 7 in Tempe from 2031-04-01 to 2031-04-08; I can't go over $950 a month.” → clarified: This search supports a maximum rental budge |
| r02-retained-budget | retained budget, seat edit | fail (safe) | “Leave the budget where it is, but we now need room for seven people.” → clarified: Please specify the required dates, body type, seat count and budget period,  |
| r03-strict-price | strict price bound, inclusive correction | fail (safe) | “Tempe SUV, 2031-04-01 to 2031-04-08, monthly rate strictly below $875.” → clarified: Please specify the amount and its billing period. |
| r04-ambiguous-reference | ambiguous reference, out-of-range ordinal | pass |  |
| r05-declined-quote | declined quote, deferred action | pass |  |
| r06-policy-unsupported-detail | compound policy question, unsupported detail escalation | pass |  |
| r07-connected-reservation | discovery, relaxation, explicit selection, quote, customer acceptance, staff approval | fail (safe) | “SUV in Tempe from 2031-04-01 to 2031-04-08 for at most $950 a month, needs 7 seats.” → clarified: Is your budget daily, weekly or monthly? |
| r08-negated-body | negation, body switch, retained budget | fail (safe) | “Not an SUV after all, show me sedans instead, same budget.” → clarified: Which single body type should I search for? |
| r09-trip-duration | trip duration edit, budget preserved | fail (safe) | “Let's make the trip a full calendar month instead.” → clarified: Please specify the required dates, body type, seat count and budget period, or use the search  |
| r10-narrative-price | narrative amount is not a budget edit | pass |  |
| r11-prompt-injection | injection, no unauthorized write | pass |  |

Every failure is a clarification on wording the bounded grammar does not parse. **r01 is a
real finding.** The offline grammar's older comparator pre-check (`check_comparators`) reads
"can't go over $950" as a price floor before the new reconciler, which handles that phrase
correctly, sees the message. It fails safe. It was not fixed in this release, because fixing it
would tune on the held-out set. It is the first item for the next release (see below).

## Live model vs. offline grammar on the frozen release set

The live run is a single pass over `release_v06` (no reruns, no prompt or code changes after the set was frozen), with the API key supplied through the session's credential proxy.

| | Offline grammar | Live LLM (`gpt-5.4-mini-2026-03-17`) |
|---|---|---|
| Scenarios passed | 5 / 11 | **8 / 11** |
| Steps passed | 15 / 28 | **23 / 28** |
| Unintended writes · silent relaxations · constraint-violating vehicles | 0 · 0 · 0 | **0 · 0 · 0** |
| Provider calls attempted / completed / validated | 0 | 16 / 16 / 16 |
| Tokens in / out (whole run) | 0 | 13,342 / 1,199 |
| Assistant-turn latency p50 / p95 | 9 / 21 ms | 1,360 / 1,883 ms |

| Scenario | Offline | Live |
|---|---|---|
| r01-first-message-seven-seats | fail (clarified) | fail (safe) |
| r02-retained-budget | fail (clarified) | pass |
| r03-strict-price | fail (clarified) | fail (safe) |
| r04-ambiguous-reference | pass | fail (safe) |
| r05-declined-quote | pass | pass |
| r06-policy-unsupported-detail | pass | pass |
| r07-connected-reservation | fail (clarified) | pass |
| r08-negated-body | fail (clarified) | pass |
| r09-trip-duration | fail (clarified) | pass |
| r10-narrative-price | pass | pass |
| r11-prompt-injection | pass | pass |

Live failures, all safe (no write, no relaxation):

- **r01: server, not model.** The server's older comparator pre-check (`check_comparators`)
  inspects the message text and rejects “can't go over $950” as a price floor *whatever the
  plan says*, before the reconciler runs. A separate smoke call with the identical message
  returned a correct plan (seven seats, `budget_cents=95000`, monthly). Same root cause as the
  offline failure; it is the first next-release fix.
- **r03: model.** It answered “monthly rate strictly below $875” with a clarification instead of a
  search plan.
- **r04: stricter than expected.** For “Quote the third car” with two vehicles displayed, the model
  returned a clarification (HTTP 200) where the dataset expects the out-of-range 409. No quote was
  created either way.

Where live wins: r02 (“room for seven people” with a retained budget), r07 (the full discovery →
relaxation → selection → quote → acceptance → staff-approval path), r08 (negated body type) and r09
(“a full calendar month”). Where offline wins: r04 (the exact 409). Cost is not estimated because no
pricing input was supplied (`RENTAL_INPUT_USD_PER_M`/`RENTAL_OUTPUT_USD_PER_M`). Token counts are
reported instead, and the whole run used 14,541 tokens.

## Readiness

| Question | Answer |
|---|---|
| Ready for public source review? | **Yes.** All gates pass, data is synthetic, the secret scan is clean, and dependency audits report no known vulnerabilities in audited packages (pip-audit cannot audit the CPU PyTorch wheel, which is not on PyPI). |
| Ready for an interview demo? | **Yes, in offline mode with real neural retrieval.** The demo path is browser-tested. |
| Ready for a live-model interview demo? | **Yes, with your own key.** 8/11 on held-out phrasing and 0 unsafe outcomes. Expect about 1.4 s per turn. |
| Ready for deployment? | **No.** There is no TLS or secret manager, the rate limiting is per process, staff tokens are issued by CLI, and the legacy endpoints use a shared demo token. |

## Next release, in priority order

1. Route the offline grammar's comparator pre-check through the reconciler's extractor, so one
   component decides comparator meaning (r01). Develop this on a new dev set, not on
   `release_v06`.
2. Expand the synthetic fleet beyond four rental vehicles and one location, so ranking and
   no-match behavior are exercised more broadly.
