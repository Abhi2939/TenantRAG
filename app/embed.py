"Embeddings, used by ingest and retrieve"

from functools import lru_cache
from fastembed import TextEmbedding
from app.config import settings

@lru_cache(maxsize=1)
def _model() -> TextEmbedding:
    return TextEmbedding(model_name=settings.embedding_model)

def embed_documents(texts: list[str]) -> list[list[float]]:
    return  [v.tolist() for v in _model().embed(texts)]

def embed_query(text:str) -> list[float]:
    return next(iter(_model().query_embed(text))).tolist()