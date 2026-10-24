# TenantRAG

A multi-tenant RAG platform where each tenant uploads documents and queries them, can optionally fine-tune its own LoRA adapter, and is served from a shared base model. Built as a personal project to learn system design: multi-tenancy, queues and workers, fine-tuning, and model serving.

> **Status:** Phase 1 in progress (single-tenant RAG). Everything after Phase 1 is planned, not built.

## Why this project

- **ML:** embeddings, retrieval, LoRA fine-tuning, evaluation
- **Backend:** APIs, auth, queues, caching, databases
- **System design:** isolation, bottlenecks, failure handling, cost tradeoffs

The goal is a measurable claim, not a buzzword stack: one base model serving many tenant adapters, with real benchmark numbers (see [Results](#results)).

## Architecture (target)

```
Tenant client -> API gateway (auth, tenant routing, rate limits)
                    |
     +--------------+------------------+
     |              |                  |
 Ingest worker  Query service     Training worker
 (chunk, embed) (RAG query path)  (LoRA fine-tuning)
     |              |                  |
     |              +--> Model server (vLLM: base model + per-tenant LoRA adapters)
     |
 Tenant-scoped state: Postgres + pgvector | Object store (docs, adapters) | Redis queue
```

**Flows**
- **Query:** gateway resolves API key to `tenant_id` -> query service retrieves tenant-filtered chunks -> model server answers with that tenant's adapter.
- **Ingest:** upload stored -> job queued -> worker chunks and embeds -> vectors written with `tenant_id`.
- **Training:** job queued -> worker trains a LoRA adapter -> stored in the object store -> version registered in Postgres -> model server loads it on demand.

**Phase 1 slice (what exists now):** Client -> FastAPI -> pgvector -> LLM.

## Key design decisions

1. **Tenant isolation:** one shared collection with a `tenant_id` filter enforced in a single data-access layer, plus Postgres row-level security as a second layer. Cross-tenant leak tests are written early.
2. **One base model, many LoRA adapters** via vLLM multi-LoRA serving, instead of one model per tenant.
3. **Training jobs are asynchronous and idempotent**, modeled as a state machine (queued, running, succeeded/failed).
4. **Rate limits and usage counters** live at the gateway.
5. **Model server and training worker sit behind interfaces**, so development can use a small model or hosted API.

## Phases

| Phase | Scope | Status |
|---|---|---|
| 1 | Single-tenant RAG: `/ingest`, `/query`, eval set, Docker, Render deploy | In progress |
| 2 | Multi-tenancy: API-key auth, tenant-scoped data, row-level security, isolation tests | Planned |
| 3 | Async ingestion: Redis queue, workers, basic observability | Planned |
| 4 | Per-tenant LoRA fine-tuning: manual run first, then pipeline; RAG vs RAG + adapter | Planned |
| 5 | Serving and scale: multi-LoRA serving, rate limits, caching, load testing, write-up | Planned |

### Phase 1 checklist
- [ ] Skeleton: FastAPI app, `/health`, Docker Compose with pgvector
- [ ] Ingest: load, chunk, embed, store, `/ingest`
- [ ] Query: embed question, top-k retrieval, LLM answer, `/query`
- [ ] Eval: ~20 Q/A pairs (including a few unanswerable), `run_eval.py`, baseline recorded
- [ ] Containerize: `docker compose up` runs everything, config via env only
- [ ] Deploy to Render with managed Postgres; `/ingest` and `/query` work on the live URL

## Stack

| Concern | Choice |
|---|---|
| API | FastAPI (Python) |
| Vector store + metadata | Postgres + pgvector |
| Embeddings | Small model via ONNX (default `bge-small-en-v1.5`, 384-d) |
| LLM (Phase 1) | Hosted API (Groq) behind a single `generate()` function |
| Packaging | Docker + Docker Compose |
| Later phases | Redis queue, MinIO, PEFT/QLoRA, vLLM, Prometheus/Grafana, Locust or k6 |

## Run locally

```bash
cp .env.example .env        # add your GROQ_API_KEY
docker compose up --build
curl localhost:8000/health  # {"status":"ok"}
```

## Repo structure

```
app/
  main.py        # FastAPI routes only
  config.py      # env-based settings
  db.py          # only module that touches the DB driver
  schemas.py     # request/response models
  embed.py       # embed(texts) -> vectors (shared by ingest and retrieve)
  ingest.py      # load, chunk, embed, store
  retrieve.py    # vector search, single entry point
  generate.py    # prompt + LLM call
eval/            # questions.json, run_eval.py
sql/init.sql     # pgvector extension, schema
data/docs/       # corpus
tests/
```

## Decisions log

| Decision | Choice | Why |
|---|---|---|
| Backend language | Python + FastAPI | ML ecosystem is Python-first; one language for API and workers |
| Vector store | Postgres + pgvector | One fewer service; reused for tenant filtering in Phase 2 |
| Embedding model | bge-small-en-v1.5 (384-d) | Small enough for Render's ~512 MB limit |
| Chunk size / overlap | 500 / 60 (starting point) | Tune using the eval set |
| Top-k | 5 (starting point) | Tune using the eval set |
| Generation LLM | _to decide_ | |
| Eval corpus | _to decide_ | |

## Results

Filled in as phases complete. No numbers are claimed until measured.

| Metric | Value |
|---|---|
| Phase 1 retrieval hit@k | _tbd_ |
| Phase 1 answer quality | _tbd_ |
| RAG vs RAG + LoRA (Phase 4) | _tbd_ |
| p95 latency at N req/s (Phase 5) | _tbd_ |

## Notes on fine-tuning

- Most RAG failures are retrieval failures. Fix chunking, retrieval, and prompts before fine-tuning.
- LoRA is for style, format, and domain behavior, not for teaching new facts.
- The eval baseline from Phase 1 is what makes any later improvement measurable, including an honest negative result.

## Deployment notes (Render)

- Build and test locally first; deploy at the end of Phase 1.
- Free instances sleep and have about 512 MB of memory, so use a small embedding model.
- Disk is ephemeral, so keep vectors in managed Postgres.
- Free databases are limited and may expire; do not treat the deployed copy as permanent storage.