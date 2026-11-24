# Engineering implementation and verification report

Release: 0.1.0, Phase 1 review candidate. Date: November 17, 2026. Author: Taksh Pathak portfolio implementation, developed with AI assistance.

## Baseline and scope

The provided workspace contained no source files. A search for Easy Route source ZIPs returned no matching code archive. There was no previous implementation available to baseline or preserve. New source was created incrementally. Existing business documents were not ingested or reused; the implementation contains synthetic inventory only.

This delivery implements the foundation vertical slice, not all seven requested phases. It must not be labeled a finished advanced AI engineering system.

## Features and architecture

FastAPI exposes inventory, session history, chat, lead creation, availability, appointment booking/cancellation and staff overview/purge. SQLAlchemy uses PostgreSQL as the source of truth. Alembic contains an explicit schema snapshot. SQLite is an additional local testing option.

A Pydantic search schema defines required inventory constraints. SQL filters availability, price ceiling, body and minimum seats. Feature matching ranks the filtered set using simple overlap, followed by price and ID. These are baseline ranking semantics, not ML relevance or neural similarity.

Session ownership is established through a random token whose SHA-256 digest is stored server-side. Sessions expire after configured inactivity. Deletion cascades to owned records. A staff-triggered purge physically removes expired sessions. Staff endpoints reject requests when the secret is unset or incorrect.

Appointments use aligned, timezone-aware hourly slots in explicit synthetic business hours (16:00–23:00 UTC). A partial unique index excludes cancelled appointments and enforces one active booking per vehicle and slot. PostgreSQL vehicle row locks serialize booking checks with future inventory modifications that use the same row. Conflict violations are rolled back and mapped to HTTP 409. Availability is advisory; insertion is authoritative.

The Next.js UI calls the backend for chat, inventory, availability, booking, cancellation, lead creation and history restoration. Vehicle comparison uses records returned by inventory. Staff operations currently displays authenticated JSON records, not a finished management dashboard.

## AI capabilities

- Deterministic test mode: narrow regex preference extraction, persistent preference carry-forward, database search, templated responses, measured per-turn latency. Clearly labeled in the API and UI.
- Optional OpenAI Responses API adapter: bounded three-round tool loop, server-side argument validation, allowlisted read-only inventory tool, 30-second HTTP timeout, provider error handling and token-usage capture.
- Saved hard constraints are applied server-side to proposed live model tool arguments, preventing silent budget relaxation. Explicit changes recognized by the deterministic grammar can update those bounds.
- No autonomous model writes: booking, lead capture and cancellation use explicit authenticated API requests.

No live provider call occurred. No neural RAG, embeddings, vector index, cross-encoder reranking, document ingestion or citations are implemented. Persistent full messages and structured preferences are implemented; generated long-term summaries are not.

## Files added

All source files are new. Primary files:

| Files | Responsibility |
|---|---|
| backend/app/config.py, db.py, models.py | Typed configuration, engine/session lifecycle, database schema |
| backend/app/schemas.py, services.py | Strict request validation, constrained inventory ranking, transactional booking |
| backend/app/ai.py | Deterministic extraction and optional live provider tool loop |
| backend/app/main.py | REST endpoints and authorization checks |
| backend/app/seed.py | Five synthetic inventory rows |
| backend/alembic/env.py, versions/0001_initial.py | Migration runner and explicit initial migration |
| backend/tests/test_workflows.py | Functional, constraint, concurrency, auth, retention and mocked-provider tests |
| backend/benchmark.py | Eight-case deterministic extraction smoke benchmark |
| frontend/app/page.tsx, layout.tsx, style.css | Integrated customer UI and staff read view |
| frontend/tests/customer.cjs, scripts/browser_e2e.py | Reproducible browser workflow runner |
| compose.yaml, backend/Dockerfile, frontend/Dockerfile | Local deployment definitions |
| .github/workflows/ci.yml | PostgreSQL backend checks and frontend production build |
| README.md, docs/* | Setup, actual evidence, limitations and reviewer guidance |

## Verification table

| Feature | Implemented | Tested | Actual result | Limitations |
|---|---|---|---|---|
| Backend startup | Yes | Yes | Uvicorn reached application startup complete; health test passed | Public deployment not tested |
| Frontend production build | Yes | Yes | Next.js 16.4.6 build and TypeScript passed | Browser interaction blocked |
| PostgreSQL migrations | Yes | Yes | Upgrade, seed and Alembic schema check passed on PostgreSQL 16.2 | Compose targets PostgreSQL 17; Compose not run |
| Inventory retrieval | Yes | Yes | Filter and availability tests passed | Synthetic five-row fixture |
| Recommendation constraints | Baseline | Yes | Price/seats/body/availability tests passed | No neural ranking or relevance benchmark |
| Persistent memory | Partial | Yes | Preference carry-forward, isolation, expiry and deletion passed | No summaries; concurrent chat ordering unresolved |
| Live LLM adapter | Yes | Mock only | Valid call/output loop, bad argument rejection and saved-budget regression passed | Zero actual model calls; model text can hallucinate |
| RAG indexing/retrieval | No | No | Not run | No embeddings, Pinecone, FAISS, hybrid search or reranker |
| Lead creation | Yes | Yes | Consent/validation and successful insert passed | No deduplication, qualification or staff updates |
| Booking/cancellation | Yes | Yes | Create, cancel, rebook and ownership passed | Fixed hourly slots; no overall staff capacity |
| Double-book prevention | Yes | Yes | Concurrent two-request test produced one 201 and one 409 on both database engines | No large stress test |
| Authorization | Partial | Yes | Session cross-access and staff access checks passed | Shared staff bearer secret; no roles/login |
| API errors | Partial | Yes | Invalid inputs, provider mock failure, conflicts and unauthorized access checked | No full fault-injection suite |
| Customer workflow via API | Yes | Yes | Discovery → memory → lead → booking → deletion passed | Deterministic mode |
| Browser customer workflow | Source provided | Attempted | BLOCKED: Chromium failed at socket creation with Operation not permitted | No browser E2E pass claimed |
| Docker/Compose | Definitions | No | Not executed; Docker unavailable | Runtime reproducibility gate remains open |
| CI | Configuration | No remote run | Workflow supplied, no GitHub push | Remote CI results unknown |
| Dependency audit | Frontend | Yes | npm audit --omit=dev reported zero known vulnerabilities | Snapshot only; backend audit not performed |

## Exact test evidence

Commands were executed from the indicated directories. Full output is included alongside this report.

### SQLite backend suite

From `backend` (suite sets its disposable SQLite URL when DATABASE_URL is unset):

```sh
python -m pytest -q
```

Actual result: **20 passed, 0 failed, 0 skipped**, two third-party deprecation warnings. Evidence: `docs/backend-tests.txt`.

### PostgreSQL validation

A local temporary PostgreSQL 16.2 server was launched using binaries supplied by pgserver 0.1.4, with UTF-8 encoding and TCP-only listening. This helper was used only for validation and is not an application dependency. The first attempt used SQL_ASCII and failed in SQLAlchemy version detection with a bytes/string error; initializing a separate UTF-8 test cluster fixed that environment issue. No application workaround was added.

With `DATABASE_URL=postgresql+psycopg://easy@127.0.0.1:5432/postgres`, from `backend`:

```sh
python -m alembic upgrade head
python -m app.seed
python -m alembic check
python -m pytest -q
```

Actual result: migration succeeded, seed succeeded, **No new upgrade operations detected**, **20 passed, 0 failed, 0 skipped**. Evidence: `docs/postgres-tests.txt`. Tests destroy/recreate their target schema; only use a disposable database.

### Frontend

From `frontend`:

```sh
npm run build
npm audit --omit=dev --json
```

Actual result: compilation, TypeScript and static page generation passed. Production dependency audit reported zero known vulnerabilities. Evidence: `docs/frontend-build.txt`, `docs/npm-audit.json`. The lockfile is included. Dependency audit is not proof of application security.

### Model and deterministic benchmark

From `backend`:

```sh
python benchmark.py
```

Actual result: **8/8 authored grammar cases matched** (exact match 1.0); recorded total elapsed 0.359 ms in this run. These tiny, deliberately supported cases are not a statistically meaningful performance claim. Evidence: `docs/deterministic-benchmark.json`. **Actual model calls: 0.** Real-model intent accuracy, groundedness, hallucination rate, retrieval Recall@K/MRR, citation accuracy, semantic recommendation relevance and model cost are **not measured**. Cost is recorded as null.

### Browser attempt

Both production frontend and API reached startup readiness in the same process environment; the runner then attempted `node tests/customer.cjs`. Chromium terminated before opening a page because its singleton socket could not be created in the sandbox. Evidence: `docs/browser-e2e.txt`, `docs/api-startup.txt`, `docs/frontend-startup.txt`. The portable reproduction command is `python scripts/browser_e2e.py` from the root after installing dependencies/building and providing Chromium. No application browser workflow was verified.

## Remaining critical and high-priority work

1. Neural RAG and held-out retrieval/citation evaluation are absent. Implement versioned synthetic policy ingestion, embedding-model configuration, FAISS then Pinecone, hybrid scoring, reranking, stable source IDs and separate retrieval benchmarks.
2. Live-model behavior is unverified. Run real provider calls with explicit credentials, evaluate tool choice, intent extraction and multi-turn constraint updates, independently check generated claims, and record actual token costs using a documented pricing date.
3. Replace shared staff secret with individual authentication and roles; add rate limits, request ceilings, secret rotation, TLS ingress, audit logs and threat-model tests. No public deployment before these controls.
4. Complete employee inventory/lead/appointment mutations, lead qualification, summaries, analytics, full tool registry and confirmed state-changing tool execution.
5. Resolve concurrent chat preference updates and session deletion/booking races. Add idempotency keys and provider retry policy; guard large histories/listings; make retention deletion policy configurable by record type.
6. Run browser E2E in an unrestricted Chromium environment; run Compose on PostgreSQL 17; validate restart/persistence, backups, CI and deployment.

## Reviewer Handoff Summary

Review the SQL hard-constraint boundary in `services.py` and live tool-argument enforcement in `ai.py` first. Verify the PostgreSQL partial unique index and cancellation semantics against real concurrent requests. Inspect session-token authorization, cascading deletion of active appointments, shared staff authentication and absent request limits. Evaluate the real-model adapter separately: mocks demonstrate orchestration only, and generated text is not guaranteed grounded. Confirm README and portfolio descriptions state Phase 1 status and do not imply neural RAG, real-model metrics, completed employee operations or historical employer achievements. Browser E2E and Compose execution remain release blockers. Nothing has been pushed to GitHub.
