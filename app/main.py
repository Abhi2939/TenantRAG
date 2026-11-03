"FastAPI app and routes only"

from contextlib import asynccontextmanager

import groq
from fastapi import FastAPI, File, HTTPException, UploadFile

from app.db import close_pool, init_db
from app.generate import generate
from app.ingest import ingest_document, load_text
from app.retrieve import retrieve
from app.schemas import IngestResponse,QueryRequest,QueryResponse

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield
    close_pool()


app = FastAPI(title="TenantRAG",lifespan=lifespan)


@app.get("/health")
def health() -> dict:
    return {"status":"ok"}

@app.post("/ingest",response_model=IngestResponse)
def ingest(file:UploadFile= File(...)) -> IngestResponse:

    name = file.filename or "uplaod.txt"
    data = file.file.read()

    try:
        text = load_text(name,data)
        doc_id, n_chunks = ingest_document(name,text)

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return IngestResponse(document_id=doc_id,source=name,chunks=n_chunks)

@app.post("/query",response_model=QueryResponse)
def query(req:QueryRequest) -> QueryResponse:
    chunks = retrieve(req.question,req.top_k)

    try:
        answer = generate(req.question, chunks)

    except RuntimeError as e:
        raise HTTPException(status_code=503,detail=str(e))

    except groq.APIError as e:
        raise HTTPException(status_code=502,detail=f"LLM provider error: {e}")
    return QueryResponse(answer=answer,sources=chunks)

