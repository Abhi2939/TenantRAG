# TenantRAG

A multi-tenant RAG platform where each tenant uploads documents and queries them, can optionally fine-tune its own LoRA adapter, and is served from a shared base model. Built as a personal project to learn system design: multi-tenancy, queues and workers, fine-tuning, and model serving.

## Why this project

- **ML:** embeddings, retrieval, LoRA fine-tuning, evaluation
- **Backend:** APIs, auth, queues, caching, databases
- **System design:** isolation, bottlenecks, failure handling, cost tradeoffs

The goal is a measurable claim, not a buzzword stack: one base model serving many tenant adapters, with real benchmark numbers (see [Results](#results)).

## Architecture (target)

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/architecture.svg">
  <img alt="TenantRAG architecture" src="docs/architecture.svg">
</picture>

Solid boxes are built in Phase 1; dashed boxes are planned for Phases 2 to 5. Phase 2 adds API-key auth inside the FastAPI app itself (a dependency that resolves the key to a `tenant_id`); a separate gateway comes in Phase 5.

**Flows**
- **Query:** the API resolves the API key to `tenant_id` -> query service retrieves tenant-filtered chunks -> model server answers with that tenant's adapter.
- **Ingest:** upload stored -> job queued -> worker chunks and embeds -> vectors written with `tenant_id`.
- **Training:** job queued -> worker trains a LoRA adapter -> stored in the object store -> version registered in Postgres -> model server loads it on demand.

**What exists now:** Client -> FastAPI (API-key auth) -> tenant-scoped pgvector (row-level security) -> LLM.

**Live demo (Phase 1):** `https://tenantrag.onrender.com/docs` (free instance: sleeps after 15 minutes idle, first request takes about a minute to wake). The live demo still runs the Phase 1 code (no authentication) until Phase 2 is deployed and verified.

## Key design decisions

1. **Tenant isolation:** one shared collection with a `tenant_id` filter enforced in a single data-access layer, plus Postgres row-level security as a second layer. Cross-tenant leak tests are written early. Details in [Multi-tenancy](#multi-tenancy).
2. **One base model, many LoRA adapters** via vLLM multi-LoRA serving, instead of one model per tenant.
3. **Training jobs are asynchronous and idempotent**, modeled as a state machine (queued, running, succeeded/failed).
4. **Rate limits and usage counters** live at the gateway.
5. **Model server and training worker sit behind interfaces**, so development can use a small model or hosted API.

## Phases

| Phase | Scope | Status |
|---|---|---|
| 1 | Single-tenant RAG: `/ingest`, `/query`, eval set, Docker, Render deploy | Complete |
| 2 | Multi-tenancy: API-key auth, tenant-scoped data, row-level security, isolation tests | Built and tested locally; deploy pending |
| 3 | Async ingestion: Redis queue, workers, basic observability | Planned |
| 4 | Per-tenant LoRA fine-tuning: manual run first, then pipeline; RAG vs RAG + adapter | Planned |
| 5 | Serving and scale: multi-LoRA serving, rate limits, caching, load testing, write-up | Planned |

### Phase 1 checklist
- [x] Skeleton: FastAPI app, `/health`
- [x] Ingest: load, chunk, embed, store, `/ingest`
- [x] Query: embed question, top-k retrieval, LLM answer, `/query`
- [x] Eval: 20 Q/A pairs (15 answerable, 5 unanswerable), `run_eval.py`, baseline recorded (see [Results](#results))
- [x] Containerize: Dockerfile and Docker Compose with pgvector; `docker compose up` runs everything, config via env only (baseline eval reproduced inside Docker)
- [x] Deploy to Render (Docker web service, Supabase Postgres); `/ingest` and `/query` work on the live URL

### Phase 2 checklist
- [x] Data model: `tenants`, `api_keys` (hash only), `tenant_id` on `documents` and `chunks`; idempotent migration that moves existing rows to a `default` tenant
- [x] Tenant and key creation through a local script (no public endpoint)
- [x] API-key authentication on `/ingest` and `/query` (401 for missing, malformed, unknown or revoked keys; `/health` stays public)
- [x] Tenant-scoped data layer: every read and write goes through `db.py`, `retrieve.py` and `ingest.py` with a required `tenant_id`
- [x] Row-level security on `documents` and `chunks`, with the API connecting as a restricted role
- [x] Leak tests at the app level and the database level
- [x] Per-tenant eval: `default` tenant matches the Phase 1 baseline
- [ ] Deploy: migrations out of app startup, restricted role on Supabase, leak tests against the deployed setup, real key verified on the live URL

## Stack

| Concern | Choice |
|---|---|
| API | FastAPI (Python) |
| Vector store + metadata | Postgres + pgvector |
| Auth | API keys (SHA-256 hash stored), FastAPI dependency |
| Isolation | `tenant_id` filter + Postgres row-level security |
| Embeddings | Small model via ONNX (default `bge-small-en-v1.5`, 384-d) |
| LLM (Phase 1) | Hosted API (Groq) behind a single `generate()` function |
| Packaging | Docker + Docker Compose |
| Later phases | Redis queue, MinIO, PEFT/QLoRA, vLLM, Prometheus/Grafana, Locust or k6 |

## Multi-tenancy

**Isolation model.** One shared schema; `documents` and `chunks` both carry a NOT NULL, indexed `tenant_id`. Chunks carry it directly so a similarity search filters and applies RLS on one table with no join. Per-tenant tables or databases isolate more strongly but cost far more at scale.

**Two layers.** (1) The data layer (`db.py`, `retrieve.py`, `ingest.py`) always filters or tags by `tenant_id`; routes never build SQL. (2) Postgres row-level security enforces the same rule inside the database, so a forgotten filter in Python still cannot leak rows.

**API keys.** `trag_` + 32 random bytes (`secrets.token_urlsafe`), shown once. Only the SHA-256 hash and an 8-character prefix are stored. A fast hash is appropriate because keys are high-entropy; slow password hashes defend low-entropy passwords. A key is revoked once `revoked_at` is set, and revoked keys never match. Missing, malformed, unknown and revoked keys all return the same 401, so a caller cannot tell them apart. Tenants are created by a local script, not an endpoint, so there is no public way to create one.

**RLS setup.** Policies on `documents` and `chunks` compare `tenant_id` with the per-transaction setting `app.tenant_id` (`set_config(..., true)`, so the value cannot leak across pooled connections). No setting means zero rows (fail closed), and `WITH CHECK` blocks writing a row tagged for another tenant. The API connects as `tenantrag_app`: not a superuser, no BYPASSRLS, not the table owner, with only the grants it needs (select and insert on the two tenant tables, and read access to three columns of `api_keys` for the key lookup). Migrations run as the table owner through `ADMIN_DATABASE_URL`. RLS is silently skipped for table owners, superusers and BYPASSRLS roles (Supabase's default `postgres` role is one of these), so the restricted role is what makes the policies real.

**Leak tests** (`tests/test_leaks.py`, local database only, throwaway tenants that are deleted afterwards).
- *App level:* retrieval and `/query` return only the caller's chunks in both directions; the same question gives each tenant its own sources; searching for the other tenant's secret finds nothing; documents ingested through `/ingest` are invisible to the other tenant; retrieval without a tenant is refused.
- *Database level, as the restricted role:* the role is not superuser, BYPASSRLS or owner; no tenant set returns zero rows; a tenant context sees only its own rows; inserting a document or chunk for another tenant is rejected; writes without a tenant are rejected; the tenant setting does not carry into the next transaction; the role cannot read `tenants` or key metadata.

**Known limits.**
- HNSW applies the tenant filter after the index search, so `hnsw.ef_search` is raised to 100 per query. Many tenants may need iterative scans (pgvector 0.8+) or partitioning.
- Foreign-key checks bypass RLS, so a chunk could reference another tenant's `document_id`. No write path accepts a document id from the caller, and a composite foreign key would close this.

## Run locally

Phase 2 needs two database logins (owner for migrations, restricted role for the API), so local setup has a few more steps than Phase 1.

```bash
cp .env.example .env                 # add your GROQ_API_KEY and the two database URLs below
docker compose up -d db              # Postgres + pgvector (published on host port 5433)
python -m scripts.setup_app_role     # creates the restricted role (prompts for its password)
python -m scripts.create_tenant "Acme Corp"      # prints an API key once; only its hash is stored
uvicorn app.main:app --reload
```

Environment (`.env`, never committed):

```
DATABASE_URL=postgresql://tenantrag_app:<app password>@localhost:5433/tenantrag
ADMIN_DATABASE_URL=postgresql://tenantrag:tenantrag@localhost:5433/tenantrag
GROQ_API_KEY=...
```

Use the API from the Swagger UI at `http://localhost:8000/docs` (click **Authorize** and paste the key), or with curl:

```bash
curl -H "Authorization: Bearer trag_..." -F "file=@data/docs/harbor_cli_guide.md" localhost:8000/ingest
curl -H "Authorization: Bearer trag_..." -H "Content-Type: application/json" \
     -d '{"question": "What is the default health check path?"}' localhost:8000/query
curl localhost:8000/health           # {"status":"ok"}  (public, no key)
```

Ingest one file at a time; ingesting the same file twice duplicates its chunks and skews retrieval scores. To add another key to a tenant use `python -m scripts.create_tenant "Acme Corp" --existing`. To revoke one, set `revoked_at` on its row in `api_keys` (the 8-character prefix identifies it).

The full-stack `docker compose up --build` path from Phase 1 has not been updated for the Phase 2 environment variables yet; that happens with the deploy step.

## Tests

```bash
python -m pytest tests               # key helpers, auth dependency, leak tests
python -m pytest tests/test_leaks.py -v
```

The leak tests need the local Docker database and refuse to run against a non-local host.

## Repo structure

```
app/
  main.py        # FastAPI routes only
  config.py      # env-based settings
  db.py          # only module that touches the DB driver; schema, RLS, tenant-scoped connections
  auth.py        # API-key dependency: Bearer key -> tenant_id (401 otherwise)
  keys.py        # key generation and hashing (pure functions)
  schemas.py     # request/response models
  embed.py       # embed(texts) -> vectors (shared by ingest and retrieve)
  ingest.py      # load, chunk, embed, store (tenant-scoped)
  retrieve.py    # tenant-scoped vector search, single entry point
  generate.py    # prompt + LLM call
scripts/
  create_tenant.py    # create a tenant and issue an API key (local only)
  setup_app_role.py   # create the restricted database role and its grants
eval/            # questions.json, run_eval.py (--tenant), check_evidence.py, results/ (saved runs)
sql/init.sql     # pgvector extension and Phase 1 schema (the Phase 2 migration lives in db.py)
data/docs/       # eval corpus (Harbor docs)
docs/            # architecture diagram (architecture.svg)
tests/           # test_keys.py, test_auth.py, test_leaks.py, ...
```

## Decisions log

| Decision | Choice | Why |
|---|---|---|
| Backend language | Python + FastAPI | ML ecosystem is Python-first; one language for API and workers |
| Vector store | Postgres + pgvector | One fewer service; reused for tenant filtering in Phase 2 |
| Embedding model | bge-small-en-v1.5 (384-d) | Small enough for Render's ~512 MB limit |
| Chunk size / overlap | 300 / 50 words (starting point) | Tune using the eval set |
| Top-k | 5 (starting point) | Tune using the eval set |
| Generation LLM | `openai/gpt-oss-120b` on Groq, reasoning effort low | Hosted, free tier, behind a single `generate()` function so it can be swapped |
| Eval corpus | Harbor docs: 2 fictional markdown files, ~1,600 words | The model cannot answer from prior knowledge, so the eval tests retrieval. The TenantRAG README was held back for Phase 2 tenant-isolation tests |
| Isolation model | One shared table with a `tenant_id` column | Simple and cheap; per-tenant tables or databases are stronger but costly at scale |
| Isolation layers | App-level filter first, row-level security second | If one layer has a bug, the other still protects |
| API key format | 32 random bytes, `trag_` prefix, shown once, SHA-256 hash stored | Keys are random, so a fast hash is enough and keeps the per-request lookup cheap |
| Tenant creation | Local script, no public endpoint | Less attack surface |
| Missing tenant context | Fail closed (zero rows, not all rows) | A bug should leak nothing |
| Database roles | Owner for migrations, restricted role (no BYPASSRLS, not owner) for the API | RLS does not apply to owners or BYPASSRLS roles, so the app must not connect as one |
| Auth failures | One identical 401 for every failure | A caller cannot distinguish a wrong key from a revoked one |

## Evaluation

`eval/questions.json` holds 20 questions over the Harbor docs: 8 direct lookups, 4 paraphrased, 3 needing two nearby facts, and 5 unanswerable. Retrieval and answers are scored separately so failures can be traced to the right stage. Since Phase 2 the eval runs as a named tenant (default: `default`, which owns the Harbor docs).

```bash
python -m eval.check_evidence                       # check evidence phrases against the docs before ingesting
python -m eval.run_eval --no-judge                  # retrieval only (hit@1, hit@k, MRR), no LLM calls
python -m eval.run_eval --no-judge --tenant default # explicit tenant
python -m eval.run_eval                             # adds LLM-judged answer accuracy and refusal accuracy
```

Each run is saved to `eval/results/` together with the config that produced it, including the tenant. The judge is the same model that generates answers, so it may grade its own style generously; spot-check saved runs by hand.

## Results

Phase 1 baseline (chunk 300 / overlap 50, top-k 5, `bge-small-en-v1.5`, `openai/gpt-oss-120b`):

| Metric | Value |
|---|---|
| Phase 1 retrieval hit@1 | 0.53 |
| Phase 1 retrieval hit@5 | 0.93 |
| Phase 1 retrieval MRR | 0.70 |
| Phase 1 answer accuracy | 0.93 (judged by the generating model) |
| Phase 1 refusal accuracy | 1.00 (5 unanswerable questions) |
| Phase 2 tenant `default` retrieval (restricted role, RLS on) | 0.53 / 0.93 / 0.70, identical to the Phase 1 baseline |
| Phase 2 leak tests (app level and database level) | All passing |
| RAG vs RAG + LoRA (Phase 4) | _tbd_ |
| p95 latency at N req/s (Phase 5) | _tbd_ |

Caveats:
- The corpus is about 7 chunks, so hit@5 covers most of it and is close to saturated. hit@1 and MRR are the more informative numbers.
- With 15 answerable questions, one question moves a score by about 7 points. Only large differences between runs are meaningful.
- Known failure: q08 ("How long does a personal API token stay valid?") misses retrieval. The evidence is in chunk 0, a long mixed chunk that ranks poorly, and the generator correctly refuses. Candidate fixes to test against this baseline: smaller chunks, and the bge query prefix for queries.
- Duplicate ingestion lowers these scores: every document stored twice put copies of the same chunk in the top 5 and pushed q05 and q08 out of range (hit@5 0.87, MRR 0.64). Check `select source, count(*) from documents group by 1;` before trusting a run.

## Notes on fine-tuning

- Most RAG failures are retrieval failures. Fix chunking, retrieval, and prompts before fine-tuning.
- LoRA is for style, format, and domain behavior, not for teaching new facts.
- The eval baseline from Phase 1 is what makes any later improvement measurable, including an honest negative result.

## Deployment notes (Render)

- Build and test locally first; deploy at the end of each phase.
- Free instances sleep and have about 512 MB of memory, so use a small embedding model.
- Disk is ephemeral, so keep vectors in managed Postgres.
- Free databases are limited and may expire; do not treat the deployed copy as permanent storage.
- The deployed Phase 1 service runs from the Dockerfile and connects to a managed Supabase Postgres (pgvector) instance through its connection pooler. Config comes from Render environment variables (`DATABASE_URL`, `GROQ_API_KEY`); the app listens on Render's `PORT`.
- Keep the production database URL only in Render's environment variables, never in a local `.env`. Running Phase 2 migrations against the shared database breaks the live Phase 1 `/ingest`, because the old code does not send a `tenant_id`.
- Phase 2 deployment (pending) needs the restricted role created on Supabase, migrations run as a separate step instead of at app startup, and Render's `DATABASE_URL` pointed at the restricted role.