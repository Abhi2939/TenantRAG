"FastAPI app and routes only"

from contextlib import asynccontextmanager

from fastapi import FastAPI, File, HTTPException, UploadFile

from app.db import close_pool, init_db
from app.ingest import ingest_document, load_text
from app.schemas import IngestResponse

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
async def ingest(file:UploadFile= File(...)) -> IngestResponse:

    data = await file.read()
    try:
        text = load_text(file.filename or "upload.txt",data)
        doc_id, n_chunks = ingest_document(file.filename or "upload.txt", text)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    
    return IngestResponse(document_id=doc_id, source=file.filename or "upload.txt", chunks=n_chunks)

