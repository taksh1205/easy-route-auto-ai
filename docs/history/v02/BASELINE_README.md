# Easy Route Auto AI v0.2

A grounded automotive assistant with live SQL recommendations, real neural policy retrieval, persistent customer preferences and explicitly confirmed business actions.

**Independent portfolio implementation by Taksh Pathak. All inventory, policies and evaluation identities are synthetic. Local review candidate; not deployment ready.** This is an upgrade of the exact reviewed v0.1 archive, not a replacement project. It is not evidence of historical employer-owned code or internship performance. See [NOTICE.md](NOTICE.md).

## What changed

The model no longer writes unrestricted text to the customer UI. It returns a typed plan. The server resolves vehicle facts against current SQL records, quotes actual policy chunks, builds explanations from vehicle attributes, and issues action-success records only after a transaction commits. A prompt is not used as the grounding boundary.

Canonical preferences support typed `set`, `clear` and `retain` operations with version checks. In live mode, a relaxation or replacement of a saved hard constraint requires an exact preference-change confirmation. The finite deterministic grammar is a separate offline testing mode, not the authority for arbitrary live language.

Neural policy retrieval uses pinned MiniLM embeddings, a persistent FAISS index, BM25, reciprocal-rank fusion, optional cross-encoder reranking and versioned source citations. Live inventory and appointment truth remains in PostgreSQL. A fail-closed Pinecone adapter is implemented but only mock-tested.

Bookings now support payload-matched idempotency, atomic rescheduling, expiring session-bound proposals and replay protection. Clearing chat does not cancel appointments, and a database RESTRICT foreign key prevents accidental cascading deletion of operational bookings.

## Actual verification

| Check | Executed result |
|---|---|
| SQLite backend suite including learned-model tests | 69 passed, 0 failed, 0 skipped |
| PostgreSQL 16.2 isolated backend suite | 65 passed, 0 failed, 4 neural tests intentionally skipped |
| Upgrade from v0.1 schema through v0.2 | Passed; seed preserved existing price/availability; Alembic check clean |
| Frontend production build and TypeScript | Passed |
| Versioned task evaluation | 17 authored scenarios passed in deterministic/local-SQL mode |
| Real local retrieval comparison | 22 unique questions, 4 configurations, 88 query/configuration executions |
| Real paid LLM and Pinecone calls | Not executed; credentials unavailable |
| Browser E2E | Blocked before navigation by Chromium socket restrictions |
| Docker Compose startup/restart | Blocked: Docker unavailable |

Test count is a count of pytest items, not 69 independent AI-quality scenarios. Provider mock tests verify orchestration and safeguards, not model quality. Evidence and exact commands: [engineering report](docs/ENGINEERING_REPORT.md), [commands](docs/v02/commands.json), [per-case outputs](docs/v02/evaluations).

On 20 positive and two negative retrieval questions, document-level Recall@3 / MRR were:

| Ranking configuration | Recall@3 | MRR | Median retrieval latency |
|---|---:|---:|---:|
| BM25 lexical | 0.90 | 0.800 | 10.46 ms |
| Dense | 0.95 | 0.858 | 10.34 ms |
| Hybrid RRF | 0.95 | 0.842 | 9.99 ms |
| Hybrid + cross-encoder | 1.00 | 0.917 | 155.91 ms |

This small authored synthetic corpus is not a production-quality benchmark. Hybrid did not improve MRR over dense. Reranking improved ranking but increased latency. The lexical ranking baseline also computes neural scores for the shared abstention diagnostic; these are not pure model-free timing measurements. Citation validity checks source identity and exact excerpts, not semantic correctness of a generated answer. See [evaluation methodology](docs/EVALUATION.md).

## Local setup

Requires Python 3.12+, Node 22+ and a disposable/demo PostgreSQL database. CPU neural models need network access on first download. No model weights are bundled.

```sh
cd backend
python -m venv .venv
. .venv/bin/activate
pip install torch==2.15.0+cpu --index-url https://download.pytorch.org/whl/cpu
pip install -r requirements.txt
export DATABASE_URL='postgresql+psycopg://USER:PASSWORD@localhost:5432/easy'
export STAFF_TOKEN='YOUR_RANDOM_LOCAL_DEMO_SECRET'
export AI_MODE=deterministic
python -m alembic upgrade head
python -m app.seed
python -m app.ingest
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

In a second terminal:

```sh
cd frontend
npm ci
npm run build
npm start -- --hostname 127.0.0.1
```

Open http://localhost:3000 and http://localhost:8000/docs. Start with `SUV under $20,000`, then `increase budget to $26,000`, `not an SUV, show sedans`, `remove my budget limit`, or `low mileage and high fuel efficiency`. Ask `What is the warranty policy?` for actual neural retrieval even in deterministic chat mode.

The backend reads `backend/.env` when started there. The root `.env.example` is a reference and Compose template; shell environment takes precedence. For SQLite-only local exploration, use `DATABASE_URL=sqlite:///./demo.db` with the same migrations and seed commands. PostgreSQL is the intended application database.

The resolved tested dependency closure is recorded in `backend/requirements.lock`. Install the CPU PyTorch wheel first, then `pip install -r requirements.lock` to reproduce those Python versions. Model identity and revision must match the index manifest. On an incompatible configuration, use a fresh RAG_PATH and rebuild explicitly; the index never silently mixes models.

## Upgrade an existing v0.1 database

Back up the database, stop the old app, install the new dependencies, then run `python -m alembic upgrade head`, `python -m app.seed`, `python -m app.ingest` from backend with the existing DATABASE_URL. Migration `0001` is unchanged. `0002` adds ranking attributes, preference versions, proposals and idempotency. `0003` protects appointment retention. See [UPGRADE.md](docs/UPGRADE.md). Reseeding fills synthetic attributes and adds fixture IDs, while preserving existing prices and availability. Do not run synthetic seeding against real business data.

## Models and retrieval

- Embedding: `sentence-transformers/all-MiniLM-L6-v2`, revision `c9745ed1d9f207416be6d2e6f8de32d1f16199bf`, 384 dimensions, L2 normalization, inner product. Maximum sequence length 256; word chunks of 100 with stride 80.
- Reranker: `cross-encoder/ms-marco-MiniLM-L-6-v2`, revision `233902d25c440f23af6f7d6e94d2946bac0bee0a`. Enable with RAG_RERANK=true. It was actually run in evaluation, but defaults off for latency.
- Local storage: immutable FAISS generations, integrity hash, model identity checks, atomic CURRENT swap and shared-reader/exclusive-writer locks. Updates and deletes rebuild the active generation and remove inactive local generations.
- Pinecone: same retrieval contract, generation namespaces, explicit remote upserts/queries/deletion. Set RAG_BACKEND=pinecone, PINECONE_HOST and PINECONE_API_KEY with a fresh RAG_PATH; provision a compatible 384-dimensional inner-product index. No fallback is reported as Pinecone success. Eventual remote consistency and cleanup failure handling require live verification.
- Ingestion: UTF-8 text represented as JSON documents with format `txt` or `md`; no PDF/HTML parser. Max 32,000 characters per document, 256KB batch text, 200 documents/2,000 chunks, 320KB HTTP body. Staff-only POST /staff/policies and DELETE /staff/policies/{doc_id}; CLI `python -m app.ingest --file corpus/synthetic_policies.json`.

The assistant preserves the original policy question and optional topic filter. Query rewriting is not implemented. Retrieved content is quoted, never executed or fed back as system instructions. A dense-similarity gate can abstain; it is a heuristic, not a proof of sufficient evidence.

## Live model mode

Set AI_MODE=openai, OPENAI_API_KEY and an account-supported OPENAI_MODEL. The adapter uses the Responses API to produce a single validated `plan_turn` call containing typed preference edits and a bounded list of backend tool requests. It does not render provider messages. There is no recursive autonomous tool loop. At most four typed backend tool requests are accepted per plan.

The tool registry includes inventory search, policy retrieval, comparison, availability and lead/booking/cancellation/rescheduling proposals. Live constraint relaxations need exact confirmation, because the server cannot prove arbitrary-language intent from a model-provided quote. Generic “yes” does not confirm anything. The deterministic grammar never constrains live parsing. Actual live inference and live model-quality evaluations remain unexecuted.

## Safe actions and privacy

Every mutation requires session ownership plus an Idempotency-Key. Exact action proposals expire after five minutes, are bound to the session and include normalized arguments. Confirm using `POST /sessions/{cid}/proposals/{pid}/confirm` with the identical kind and arguments. Replays using a new key are rejected; retrying the exact successful request with the original key returns the original committed result. Reusing a key for a different payload fails. Read current booking status separately: an original idempotent response is a snapshot, not a live status query.

Booking is one active appointment per vehicle per hourly slot, 09:00–16:00 America/Phoenix, within 30 days. There is no global employee-capacity model. Atomic rescheduling either moves the existing booking or leaves it unchanged. No purchase or loan is executed.

DELETE /sessions/{cid} clears messages, canonical preferences, proposals and personal lead contact records. It preserves minimal ownership, appointments and operational idempotency data. The token remains usable for operational appointment management after chat expiry. An operator invokes DELETE /staff/expired to purge expired chat data. Automatic cleanup scheduling, operational-record retention duration and customer token recovery are not implemented. Keep the session token; clearing browser storage loses self-service booking access in this demo.

## Reproduce validation safely

**Unset DATABASE_URL before running tests or task/browser evaluators.** Tests refuse an arbitrary application URL and allocate their own temporary database. They never accept DATABASE_URL as the destruction target.

```sh
cd backend
unset DATABASE_URL
EASY_RUN_NEURAL=1 HF_HUB_DISABLE_XET=1 python -m pytest -q
python benchmark.py
python evaluate.py tasks
python evaluate.py retrieval --rerank
python evaluate.py live
```

The live evaluator records `unexecuted` without credentials. To test PostgreSQL, set EASY_TEST_POSTGRES_ADMIN_URL to a test server where the runner may create/drop a uniquely named `easy_test_*` database, then run pytest. The generated database is removed afterwards. Or install pgserver and run `python scripts/verify_postgres.py` from the root; that utility owns an entirely temporary PostgreSQL cluster and checks v0.1 upgrade preservation as well.

Run `python scripts/verify_release.py` for local checks with exit codes, and `python scripts/browser_e2e.py` for Chromium E2E after a frontend build. The browser runner owns a temporary database/index. Set CHROMIUM_PATH if using a system Chromium. For Playwright's bundled browser, run `npx playwright install chromium` from frontend first.

## Docker and CI

`cp .env.example .env`, edit POSTGRES_PASSWORD and STAFF_TOKEN, then `docker compose up --build`. Use URL-safe random password characters or correctly URL-encode DATABASE_URL credentials. API/web ports bind to loopback. Named volumes persist PostgreSQL, policy index and model cache. Model download and ingestion occur before API startup. The browser URL/CORS defaults assume localhost; remote hosting requires explicit API URL and CORS configuration.

Docker was unavailable here. The exact manual startup/restart/persistence validation checklist is in [UPGRADE.md](docs/UPGRADE.md); do not claim it passed. The GitHub Actions workflow includes safe PostgreSQL tests, migrations, actual neural checks, retrieval evaluation, frontend build/type checks, browser E2E, a limited secret-pattern scan and dependency audits. It has not run remotely. Nothing has been pushed to GitHub.

## Release limits

No live LLM/Pinecone validation; browser E2E and Compose runtime remain blocked. Staff access still uses a shared local-demo token, not individual identities or roles. Request throttling is in-process, not distributed. There is no completed employee-management dashboard, account recovery, production deployment, external observability, autonomous write agent, trained vehicle ranker or statistically validated model quality. Keep access local. See severity-ranked limitations in the engineering report.

Original repository code and synthetic fixtures: MIT. Third-party models and dependencies retain their upstream licenses.
