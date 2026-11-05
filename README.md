# TenantRAG

A multi-tenant RAG platform where each tenant uploads documents and queries them, can optionally fine-tune its own LoRA adapter, and is served from a shared base model. Built as a personal project to learn system design: multi-tenancy, queues and workers, fine-tuning, and model serving.

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

**Live demo (Phase 1):** `https://tenantrag.onrender.com/docs` (free instance: sleeps after 15 minutes idle, first request takes about a minute to wake).

## Key design decisions

1. **Tenant isolation:** one shared collection with a `tenant_id` filter enforced in a single data-access layer, plus Postgres row-level security as a second layer. Cross-tenant leak tests are written early.
2. **One base model, many LoRA adapters** via vLLM multi-LoRA serving, instead of one model per tenant.
3. **Training jobs are asynchronous and idempotent**, modeled as a state machine (queued, running, succeeded/failed).
4. **Rate limits and usage counters** live at the gateway.
5. **Model server and training worker sit behind interfaces**, so development can use a small model or hosted API.

## Phases

| Phase | Scope | Status |
|---|---|---|
| 1 | Single-tenant RAG: `/ingest`, `/query`, eval set, Docker, Render deploy | Complete |
| 2 | Multi-tenancy: API-key auth, tenant-scoped data, row-level security, isolation tests | Planned |
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

Ingest through the Swagger UI at `http://localhost:8000/docs` (POST `/ingest`, one file at a time; ingesting the same file twice duplicates its chunks). Run the eval inside the container with `docker compose exec api python -m eval.run_eval`.

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
eval/            # questions.json, run_eval.py, check_evidence.py, results/ (saved runs)
sql/init.sql     # pgvector extension, schema
data/docs/       # eval corpus (Harbor docs)
tests/
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
| Eval corpus | Harbor docs: 2 fictional markdown files, ~1,600 words | The model cannot answer from prior knowledge, so the eval tests retrieval. The TenantRAG README is held back for Phase 2 tenant-isolation tests |

## Evaluation

`eval/questions.json` holds 20 questions over the Harbor docs: 8 direct lookups, 4 paraphrased, 3 needing two nearby facts, and 5 unanswerable. Retrieval and answers are scored separately so failures can be traced to the right stage.

```bash
python -m eval.check_evidence          # check evidence phrases against the docs before ingesting
python -m eval.run_eval --no-judge     # retrieval only (hit@1, hit@k, MRR), no LLM calls
python -m eval.run_eval                # adds LLM-judged answer accuracy and refusal accuracy
```

Each run is saved to `eval/results/` together with the config that produced it. The judge is the same model that generates answers, so it may grade its own style generously; spot-check saved runs by hand.

## Results

Phase 1 baseline (chunk 300 / overlap 50, top-k 5, `bge-small-en-v1.5`, `openai/gpt-oss-120b`):

| Metric | Value |
|---|---|
| Phase 1 retrieval hit@1 | 0.53 |
| Phase 1 retrieval hit@5 | 0.93 |
| Phase 1 retrieval MRR | 0.70 |
| Phase 1 answer accuracy | 0.93 (judged by the generating model) |
| Phase 1 refusal accuracy | 1.00 (5 unanswerable questions) |
| RAG vs RAG + LoRA (Phase 4) | _tbd_ |
| p95 latency at N req/s (Phase 5) | _tbd_ |

Caveats:
- The corpus is about 7 chunks, so hit@5 covers most of it and is close to saturated. hit@1 and MRR are the more informative numbers.
- With 15 answerable questions, one question moves a score by about 7 points. Only large differences between runs are meaningful.
- Known failure: q08 ("How long does a personal API token stay valid?") misses retrieval. The evidence is in chunk 0, a long mixed chunk that ranks poorly, and the generator correctly refuses. Candidate fixes to test against this baseline: smaller chunks, and the bge query prefix for queries.

## Notes on fine-tuning

- Most RAG failures are retrieval failures. Fix chunking, retrieval, and prompts before fine-tuning.
- LoRA is for style, format, and domain behavior, not for teaching new facts.
- The eval baseline from Phase 1 is what makes any later improvement measurable, including an honest negative result.

## Deployment notes (Render)

- Build and test locally first; deploy at the end of Phase 1.
- Free instances sleep and have about 512 MB of memory, so use a small embedding model.
- Disk is ephemeral, so keep vectors in managed Postgres.
- Free databases are limited and may expire; do not treat the deployed copy as permanent storage.
- The deployed Phase 1 service runs from the Dockerfile and connects to a managed Supabase Postgres (pgvector) instance through its connection pooler. Config comes from Render environment variables (`DATABASE_URL`, `GROQ_API_KEY`); the app listens on Render's `PORT`.