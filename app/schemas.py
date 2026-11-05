
from pydantic import BaseModel,Field


class IngestResponse(BaseModel):
    document_id: int
    source: str
    chunks: int

class QueryRequest(BaseModel):
    question: str = Field(min_length=1)
    top_k: int | None = Field(default=None,ge=1,le=20)

class Source(BaseModel):
    chunk_id: int
    document_id: int
    source: str
    chunk_index: int
    distance: float
    text: str

class QueryResponse(BaseModel):
    answer: str
    sources: list[Source]