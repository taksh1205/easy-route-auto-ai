# Upgrade and runtime verification

## v0.1 → v0.2

1. Back up the existing PostgreSQL database; stop the old application while migrating. Confirm the backup restore procedure independently.
2. Install Python dependencies and CPU PyTorch using README commands. `requirements.lock` records the tested application dependency closure; the +cpu wheel needs the documented PyTorch index.
3. Keep the existing DATABASE_URL. From backend, run `python -m alembic upgrade head`.
4. For the synthetic demo only, run `python -m app.seed`. It fills mileage/mpg and adds fixture rows without overwriting existing SQL prices/availability. Synthetic fixture IDs must not be applied to a real customer inventory.
5. Set RAG_PATH to a writable persistent directory. Run `python -m app.ingest`. First download requires network access. A fresh path is required if changing the embedding identity/backend.
6. Start the backend and rebuilt frontend. The API contract now requires Idempotency-Key for mutations and provides versioned session state. Prefer the proposal/confirm endpoints used by the new UI.

Migration 0001 is byte-for-byte preserved. Migration 0002 adds nullable ranking attributes, conversation.version, action_proposals and idempotency. Migration 0003 replaces the appointment ownership cascade with a named RESTRICT foreign key; SQLite uses Alembic batch alteration. Existing appointment rows and the active-slot unique index are retained. Downgrades exist, but rollback of schema is not a substitute for an application-compatible backup. Do not downgrade a database with v0.2 operational data without reviewing what would be discarded.

The executed PostgreSQL utility created a fresh local PostgreSQL 16.2 cluster, applied 0001, inserted a v0.1 synthetic vehicle with an edited price/unavailable status, upgraded to head, reseeded and asserted that price/availability survived while mileage was added. Alembic check reported no new operations. It then allocated a separate random test database for tests. Logs and command exit codes are in docs/v02/postgres-*.

## SQLite migration verification

Use a newly allocated scratch database, not an existing application URL:

```sh
cd backend
DATABASE_URL=sqlite:////tmp/easy_upgrade_demo.db python -m alembic upgrade head
DATABASE_URL=sqlite:////tmp/easy_upgrade_demo.db python -m app.seed
DATABASE_URL=sqlite:////tmp/easy_upgrade_demo.db python -m alembic check
```

The browser runner actually migrated its owned temporary SQLite database before Chromium startup was blocked. Unit tests deliberately allocate their own schema; they are not a substitute for migration checks.

## Docker Compose manual acceptance gate — not executed here

Docker is unavailable in the authoring environment. The following remains a reviewer/runtime gate:

```sh
cp .env.example .env
# Edit POSTGRES_PASSWORD and STAFF_TOKEN.
docker compose up --build -d
docker compose ps
docker compose logs migrate index api web
curl -fsS http://localhost:8000/health
curl -fsS -H 'Origin: http://localhost:3000' -D - http://localhost:8000/inventory
```

Verify: db becomes healthy, migrate completes, index completes with model identity, API is healthy, web loads, and the CORS allow-origin is exactly the configured frontend origin. Complete a booking via the UI, note its committed record ID, reload the page and confirm it remains. Then:

```sh
docker compose restart api web db
```

Verify the same appointment remains, the index is readable and prices/availability still resolve from SQL. A brief API outage during the database restart must not be reported as a successful request. Restarting containers preserves volumes; never use `down -v` as a persistence test. Verify the read-only and confirmation workflows again, test a duplicate slot, and cancel only through an explicit action. This entire Compose sequence is unverified until actually run.

Compose publishes API/web on loopback only and does not publish PostgreSQL. Remote hosting requires an explicit public API base URL at frontend build time, matching CORS_ORIGIN, individual staff authentication/roles, TLS ingress and reviewed operational configuration. Current Compose definitions are for local portfolio exploration, not a production deployment claim.

## v0.5.1 → v0.6.0

No schema migration. Alembic head is unchanged (`0004`); `alembic check` is clean.

1. **Saved searches are compatible.** Existing `budget_cents` values keep their inclusive meaning
   (`rate <= budget_cents`). New searches phrased with a strict bound ("under $875") are saved as the
   exact inclusive ceiling `87499`. Because currency is integer cents, `rate < X` and `rate <= X - 1`
   select identical rows.
2. **Configuration.** `AI_MODE` accepts `deterministic` (default), `openai` or `anthropic`. The live
   modes read `OPENAI_API_KEY`/`OPENAI_MODEL` or `ANTHROPIC_API_KEY`/`ANTHROPIC_MODEL`. The legacy
   dealership assistant (`/sessions/{id}/chat`) remains OpenAI-only.
3. **Containers.** Rebuild the backend image. v0.5.x mounted the `modelcache` volume over a path that did
   not exist in the image, so Docker created it root-owned and the non-root `index` service could not
   download the embedding model. The image now creates `/home/app/.cache` owned by `app`. Remove an
   existing root-owned volume once: `docker compose down && docker volume rm <project>_modelcache`.
4. **API additions (backward compatible).** `/rental-discovery` and edit responses from `/rentals/ask`
   include `reconciliation.overrides`; `GET /sessions/{id}/rentals` includes `model`.
