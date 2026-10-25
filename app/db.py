from contextlib import contextmanager

from pgvector.psycopg import register_vector
from psycopg_pool import ConnectionPool

from app.config import settings

_pool: ConnectionPool | None = None


def _configure(conn):
    register_vector(conn)


def get_pool() -> ConnectionPool:
    global _pool
    if _pool is None:
        _pool = ConnectionPool(
            settings.database_url, min_size=1, max_size=5,
            configure=_configure, open=False,
        )
        _pool.open(wait=True, timeout=30)
    return _pool


@contextmanager
def connection():
    with get_pool().connection() as conn:
        yield conn


def init_db() -> None:
    """Create extension and tables if missing. Safe to call on every startup."""
    
    import psycopg
    with psycopg.connect(settings.database_url, autocommit=True) as conn:
        conn.execute("CREATE EXTENSION IF NOT EXISTS vector")

    dim = settings.embedding_dim
    with connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS documents (
                id         BIGSERIAL PRIMARY KEY,
                source     TEXT NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
        conn.execute(
            f"""
            CREATE TABLE IF NOT EXISTS chunks (
                id          BIGSERIAL PRIMARY KEY,
                document_id BIGINT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
                chunk_index INT NOT NULL,
                text        TEXT NOT NULL,
                embedding   vector({dim}) NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS chunks_embedding_idx
            ON chunks USING hnsw (embedding vector_cosine_ops)
            """
        )


def close_pool() -> None:
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None