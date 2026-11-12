from contextlib import contextmanager

from pgvector.psycopg import register_vector
from psycopg_pool import ConnectionPool

from app.config import settings

DEFAULT_TENANT = "default"

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
        # tenant and their API keys
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
            """
            CREATE TABLE IF NOT EXISTS api_keys (
                id         BIGSERIAL PRIMARY KEY,
                tenant_id  BIGINT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
                key_hash   TEXT NOT NULL UNIQUE,   -- SHA-256 of the key; the key itself is never stored
                key_prefix TEXT NOT NULL,          -- first few characters, to recognise a key in lists
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                revoked_at TIMESTAMPTZ
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS api_keys_tenant_idx ON api_keys(tenant_id)")
        conn.execute(
            "INSERT INTO tenants (name) VALUES (%s) ON CONFLICT (name) DO NOTHING",
            (DEFAULT_TENANT,),
        )

        # document and chunks
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

        # every row belongs to tenant
        for table in ("documents", "chunks"):
            conn.execute(
                f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS tenant_id "
                "BIGINT REFERENCES tenants(id) ON DELETE CASCADE"
            )
            conn.execute(
                f"UPDATE {table} SET tenant_id = (SELECT id FROM tenants WHERE name = %s) "
                "WHERE tenant_id IS NULL",
                (DEFAULT_TENANT,),
            )
            conn.execute(f"ALTER TABLE {table} ALTER COLUMN tenant_id SET NOT NULL")
            conn.execute(f"CREATE INDEX IF NOT EXISTS {table}_tenant_idx ON {table}(tenant_id)")

        
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS chunks_embedding_idx
            ON chunks USING hnsw (embedding vector_cosine_ops)
            """
        )

def get_default_tenant_id() -> int:
    with connection() as conn:
        return conn.execute(
            "SELECT id FROM tenants WHERE name = %s", (DEFAULT_TENANT,)
        ).fetchone()[0]

def close_pool() -> None:
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None