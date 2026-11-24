# Easy Route Auto AI v0.2 — engineering and verification report

Review candidate, November 17, 2026 (America/Phoenix; execution logs use UTC). This is an incremental upgrade of the exact `Easy_Route_Auto_v0.1.0_Review.zip` archive with SHA-256 `bd32474cd33b1e2195b68ab36669aa62d82d27c22a72e30bfb84af2972971333`. Its source was recovered and its 20 baseline tests were rerun successfully before modification. The existing FastAPI, SQLAlchemy, initial migration, token ownership, SQL inventory constraints, booking uniqueness and Next.js application were preserved and extended.

This is a materially stronger AI engineering review candidate, not a production-ready release. No GitHub push or deployment occurred. Original implementation and fixtures are MIT-licensed; all business data is synthetic. Neither this new code nor its metrics establish historical employer accomplishments.

## Implemented changes

1. **Grounded response boundary.** `ai.py` no longer displays arbitrary provider prose. `TurnPlan` excludes free factual prose/prices/action success fields. `AssistantResult` separates SQL records, evidence, proposals and committed actions. Unsupported message-only provider output becomes a fixed clarification. Unknown factual plan fields are rejected. Inventory lookup runs server-side for non-greeting turns even when the model omits tools; impossible constraints produce no matches. Ordinary exact greetings do not call SQL inventory.
2. **Typed preferences.** New canonical fields and explicit set/clear/retain edits preserve unrelated constraints. Offline grammar now handles the reported negation, decimal price and removal cases, plus low mileage/fuel efficiency. Live planning uses typed updates and current-message evidence, never regex enforcement. Saved hard-constraint relaxation/replacement needs exact authenticated preference confirmation; contradictory edits are rejected. Compare-and-swap versioning prevents simultaneous turns from silently overwriting each other. Inference holds no database locks/read transaction.
3. **Actual neural policy RAG.** TXT/Markdown JSON ingestion, size limits, stable IDs/versions/chunking, batched learned embeddings, persistent FAISS, BM25, RRF hybrid search, optional pinned cross-encoder, metadata filters and quoted citations are integrated into the assistant. Learned embedding, retrieval, index persistence, update/delete and reranking paths actually executed locally. Pinecone implements the same contract with explicit failures/no silent fallback, but only mock HTTP tests ran for Pinecone.
4. **Grounded ranking.** Nullable mileage/mpg attributes and 12 synthetic records exercise price, availability, seat count, missing values and ranking trade-offs. SQL hard filters precede transparent normalized scoring; feature, mileage, mpg and optional neural-semantic components have configurable weights and stable ties. Explanations use actual attributes. No trained ranker is claimed.
5. **Provider reliability.** Typed envelope/output/usage validation handles wrong JSON shapes, malformed JSON, missing IDs, unknown tools and bad arguments. A single typed planning call replaces the recursive tool-loop design; at most four typed internal tools and three transient HTTP attempts are accepted. Retries use bounded exponential backoff, an overall deadline and controlled errors. No blind write retries. Request IDs, model identity, usage, nullable cost, retry counts and tool timings are recorded without credentials/raw model prose in diagnostic telemetry.
6. **Typed tools and confirmation.** Inventory, policy retrieval, comparison, availability and lead/booking/cancellation/reschedule proposal tools reuse existing backend services. Five-minute session-bound proposals require exact kind/arguments plus session ownership to confirm. Altered/expired/cross-session/replayed requests are rejected. Committed results carry record IDs; failed transactions cannot produce success records. Same successful idempotency key/payload returns the original result.
7. **Operational reliability and privacy.** Booking idempotency and atomic rescheduling preserve the active-slot uniqueness rule. Business timezone is explicitly America/Phoenix with per-vehicle hourly capacity. Chat deletion/expiry clears personal chat/lead data without cancelling appointments; a RESTRICT ownership foreign key prevents cascade deletion at DB level. Tests allocate disposable databases and refuse arbitrary DATABASE_URL values before engine import. Booking tests use an injectable fixed clock.
8. **Integration.** Frontend components now show source excerpts and ranking explanations, exact proposal review and committed record statuses. It recovers malformed/missing stored sessions, restores current inventory/version/appointments, separates success/error notifications and clears comparison/booking-selection state on chat reset. Historical proposals hydrate their consumed/expired state. Request body limits, in-process throttling and output pagination are implemented. Staff identity/roles remain deferred with local-demo labeling.

## Architecture and files

See ARCHITECTURE.md for data flow, grounding limits, ranking formula, retrieval lifecycle and transaction boundaries. Migration chain: unchanged 0001 → 0002 (attributes/version/proposals/idempotency) → 0003 (appointment retention FK). See UPGRADE.md for upgrade and reproducible local/Compose commands. The source difference list (v02/changes-from-v01.json) and full checksums accompany this report.

| Principal paths | Change |
|---|---|
| backend/app/ai.py, provider.py, schemas.py | Typed plan/result and provider validation; removed raw model reply rendering |
| backend/app/preferences.py | Canonical operations, offline grammar and hard-relaxation detection |
| backend/app/rag.py, ingest.py, corpus/* | Real learned retrieval, index lifecycle and safe synthetic corpus ingestion |
| backend/app/models.py, seed.py, services.py, clock.py | Attributes, ranking, retained ownership, proposals, idempotency, booking/rescheduling and injectable clock |
| backend/app/tools.py, main.py | Integrated registry, short transactions, CAS, confirmed actions, retention, limits and routes |
| backend/alembic/versions/0002*, 0003* | Incremental schema changes |
| backend/tests/*, evaluate.py, evaluation/* | Safety-guarded tests, per-case task/retrieval evaluation and optional live diagnostics |
| frontend/lib/api.ts, components/*, app/page.tsx | Typed client state, visible evidence/proposals and current SQL inventory |
| scripts/*, .github/workflows/ci.yml, Dockerfiles, compose.yaml | Reproduction, scans, PostgreSQL upgrade utility and local runtime definitions |
| README.md, NOTICE.md, LICENSE, docs/* | Accurate claims, licensing, upgrade, methodology and reviewer evidence |

## Feature matrix

“Locally tested” includes real local SQL and, where named, actual learned model inference. “Mocked” never means live provider behavior was validated.

| Feature | Inspected | Implemented | Mocked coverage | Locally tested | Live-model/service tested | Blocked or incomplete |
|---|---|---|---|---|---|---|
| Grounding boundary | Yes | Yes | Injected unsupported facts/actions | Regression suite | No generative model | Language interpretation unverified |
| Preference edits/CAS | Yes | Yes | Live-path planning and concurrent inference | Deterministic sequences; two DB engines | No generative model | Arbitrary-language ambiguity still depends on planner |
| Neural embeddings/FAISS | Yes | Yes | No substitute used | Actual MiniLM, ingestion, queries, update/delete | Actual local learned model | First download needs network |
| BM25/dense/hybrid/reranking | Yes | Yes | None used for reported metrics | 22 queries × four configs | Actual MiniLM and cross-encoder | Small authored corpus; no real-customer validation |
| Pinecone | Yes | Yes | REST contract/failure tests | HTTP mocks only | No | Credentials, eventual consistency and reconciliation unverified |
| SQL vehicle ranking | Yes | Yes | No SQL mocks | Constraints, controlled ranking changes, real semantic score test | Actual local encoder for optional semantic component | No trained ranker or broad relevance study |
| Provider reliability | Yes | Yes | Malformed envelopes, errors, deadlines/retries | Mock transport/planner tests | No | No real account-supported model call |
| Proposed/confirmed actions | Yes | Yes | Model-plan proposals | Actual SQL commit/error/idempotency tests | Not model-autonomous writes | No account recovery; no purchase/loan actions |
| Booking/rescheduling | Yes | Yes | No SQL mocks | SQLite/PostgreSQL concurrency and failed-move rollback | Not applicable | Per-vehicle capacity only |
| Retention | Yes | Yes, explicit separation | None | Chat purge/deletion and DB RESTRICT tests | Not applicable | No automatic scheduler or final operational retention duration |
| Safe tests | Yes | Yes | Bad URL refusal subprocess | Disposable SQLite/PostgreSQL targets | Not applicable | PostgreSQL admin must be permitted to create temporary DBs |
| Frontend integration | Yes | Yes | No browser pass substituted | Build/type checks and production server startup | Not applicable | Chromium failed before navigation; UI interaction remains unverified |
| Staff auth/roles | Yes | Partial | Token authorization tests | Shared-token local demo | Not applicable | Individual users/roles not implemented; no public deployment |
| Body/rate/output limits | Yes | Yes | None | Body/rate/filter/page validation | Not applicable | In-process throttle; inventory ranking loads all qualified rows |
| Docker/CI | Yes | Definitions | None | No Docker/remote CI pass | Not applicable | Docker unavailable; remote workflow never run |
| Secret/dependency scans | Yes | Basic secret patterns + resolved dependency audit | None | No key-pattern findings; zero known vulns among auditable packages | Advisory service accessed | CPU PyTorch wheel skipped; limited pattern scanner |

## Executed verification and evidence

All final pytest items passed; warnings are third-party deprecations. No live paid inference or Pinecone calls occurred. Expected PostgreSQL constraint errors in the server log are exercised negative tests, not suite failures.

| Command / working directory | Exit | Actual result | Evidence |
|---|---:|---|---|
| `DATABASE_URL=sqlite:////tmp/easy-v01-baseline-test.db python -m pytest -q` / original backend | 0 | Original 20 passed before upgrade | v02/baseline-tests.txt |
| `EASY_RUN_NEURAL=1 HF_HUB_DISABLE_XET=1 python -m pytest -q --junitxml=../docs/v02/backend-junit.xml` / backend | 0 | 69 passed, zero failed/skipped; includes four actual learned-model tests | v02/backend-neural-tests.txt, backend-junit.xml |
| `python scripts/verify_postgres.py` / root | 0 | Temporary PostgreSQL 16.2; v0.1→head migration, seed preservation and clean schema check; 65 tests passed, four neural tests explicitly skipped | v02/postgres-run.txt, postgres-tests.txt, postgres-commands.json |
| `python scripts/verify_sqlite_upgrade.py` / root | 0 | Existing v0.1 booking preserved through SQLite batch migration; clean schema check and RESTRICT verified | v02/sqlite-upgrade.txt, sqlite-upgrade-commands.json |
| `python benchmark.py` / backend | 0 | Original eight grammar smoke cases matched | v02/deterministic-smoke.txt |
| `python evaluate.py tasks` / backend | 0 | 17 deterministic/local-SQL scenarios passed; zero skipped/failed | v02/tasks-run.txt, evaluations/tasks.json |
| `HF_HUB_DISABLE_XET=1 python evaluate.py retrieval --rerank` / backend | 0 | Actual local models, 22 unique questions and 88 query/config executions | v02/retrieval-run.txt, evaluations/retrieval.json |
| `python evaluate.py live` / backend | 0 | Explicitly unexecuted: no credentials/model; zero calls | v02/evaluations/live.json |
| `npm run build` / frontend | 0 | Next.js 16.4.6 production build passed | v02/frontend-build.txt |
| `npm run typecheck` / frontend | 0 | TypeScript passed | v02/frontend-typecheck.txt |
| `CHROMIUM_PATH=/usr/bin/chromium python scripts/browser_e2e.py` / root | 1 | Setup migrations/seed/neural ingestion succeeded, both servers started; Chromium socket creation failed before navigation | v02/browser-commands.json, browser-e2e.txt, browser-run.txt, startup logs |
| `python scripts/scan_secrets.py` / root | 0 | No supported credential-pattern findings | v02/secret-scan.txt |
| `npm audit --omit=dev --json` / frontend | 0 | Zero reported production dependency vulnerabilities | v02/frontend-audit.txt |
| `python -m pip_audit --no-deps --disable-pip -r requirements.lock --format json` / backend | 0 | 62 resolved packages: 61 audited, no known vulnerabilities; CPU PyTorch 2.15.0+cpu could not be audited from PyPI | v02/backend-audit.json, backend-audit-stderr.txt |
| Docker Compose | — | Not executed: Docker executable unavailable | v02/commands.json and UPGRADE.md |

The final command manifest and PostgreSQL/browser manifests record executable arguments, working directories and exit codes. Local utilities are supplied so another reviewer can reproduce the checks without using private temporary paths. The PostgreSQL helper requires `pip install pgserver`. The first neural-load attempt failed because socksio was absent; installation of that transport dependency allowed actual model downloads. That environment issue was not counted as a neural pass or hidden as a mock.

## Evaluation findings

Pinned embedding identity: all-MiniLM-L6-v2 at c9745ed1d9f207416be6d2e6f8de32d1f16199bf, 384 dimensions, L2, inner product. Pinned cross-encoder revision: 233902d25c440f23af6f7d6e94d2946bac0bee0a. Actual dependency versions and dataset hashes are saved.

| Configuration | Recall@3 | MRR | nDCG@3 | p50 / p95 latency |
|---|---:|---:|---:|---|
| Lexical | 0.90 | 0.800 | 0.826 | 10.46 / 13.27 ms |
| Dense | 0.95 | 0.858 | 0.882 | 10.34 / 12.76 ms |
| Hybrid | 0.95 | 0.842 | 0.870 | 9.99 / 12.52 ms |
| Hybrid + reranker | 1.00 | 0.917 | 0.938 | 155.91 / 185.72 ms |

These are document-level binary-relevance metrics on 20 positive authored questions, with two additional negative questions for abstention checks. Lexical misses two positives; dense/hybrid miss one each. Hybrid did not outperform dense. Exact source/excerpt validity was 1.0; that is not proof of semantic answer quality. Expected-phrase coverage was 0.90/0.95/0.95/1.00. Both negative examples abstained under the shared threshold; this is far too small to establish robust insufficiency detection. Lexical also computes dense diagnostics, so its latency is not a pure BM25-only baseline.

The task dataset has 17 unique scenarios and 17 executed passes, not a live AI quality score. Pytest includes multiple parameterized robustness cases; its 69 items are not presented as 69 unique customer scenarios. Live generative intent/tool accuracy, real-model hallucination rate, broad task completion and paid cost remain unmeasured. Cost values are null, not invented zeros. See EVALUATION.md for definitions and reproducibility limits.

## Remaining limitations, ranked

### Critical before any public deployment

- Individual staff authentication, roles, recovery and audit-event handling are not implemented. Shared-token access is explicitly local-demo only. No public deployment is approved or performed.
- Live generative-model inference/semantic quality and live Pinecone behavior are unverified. Mock tests cannot close this gate.
- Chromium E2E and Docker Compose startup/restart/persistence checks remain blocked. A successful frontend build is not a browser workflow pass.

### High priority

- The live evaluator records diagnostic plans/usage but does not yet compute complete gold-scored live preference/tool/task quality. Add explicit live judgments and expand genuinely distinct held-out cases.
- Evidence insufficiency uses a similarity heuristic. Expand negative/topic-shift/adversarial evaluation and independently judge whether excerpts answer the question. Policy text remains extractive rather than arbitrary generated prose.
- Operational appointment retention has no final purge duration; token recovery and automatic chat cleanup scheduling are absent. Minimal ownership anchors persist to preserve booking access.
- Pinecone generation cleanup failures are reported; retries/reconciliation, eventual-consistency polling and remote update/delete correctness need real tests. Local FAISS lifecycle is the verified path.
- In-process rate limiting and local file locks are single-host controls. Multi-worker/distributed deployment, large-corpus ingestion, and scalable inventory ranking remain engineering work.
- Staff lead/inventory/appointment management, automatic qualification, conversation summaries and operational analytics are not a finished employee product.

### Medium priority

- The deterministic grammar is intentionally finite; unsupported language clarifies rather than claiming full NLU. Live relaxations require confirmation and may be more conservative than an ideal conversational flow.
- Index rebuilds are whole-corpus operations. Failed pre-swap writes may leave orphan generations requiring operator cleanup; only the previously active generation is automatically removed, and unrelated directories are preserved. No PDF ingestion, query rewriting or incremental embedding cache is claimed.
- Dependency audit skipped the CPU-specific PyTorch wheel and used an installed-version closure without artifact hashes. The basic secret-pattern scan is narrower than a full professional secret audit.
- No external tracing/cost-pricing integration, retry-after-aware provider policy, production load test, trained vehicle ranker or statistical relevance study is provided.

## Reviewer Handoff Summary

First attempt the original unsupported-claim exploit and malformed provider envelopes: no raw model text should reach the UI. Inspect the typed plan schema, mandatory SQL lookup and server-authored result assembly. Then verify live preference relaxations require exact version-bound confirmation and run simultaneous inference updates without client versions. Test proposals with altered payload types, expiry, cross-session ownership, replay and transaction failure; verify no success record is returned on failure. Inspect the PostgreSQL partial unique index, atomic rescheduling, idempotency reservation and RESTRICT retention migration. Reproduce actual learned retrieval/update/delete and review per-case misses, latency trade-offs and the abstention limits. Finally run Chromium and Compose in a suitable environment, then perform live provider/Pinecone testing before approving stronger readiness claims. Nothing has been pushed to GitHub.
