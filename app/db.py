
from contextlib import contextmanager

from pgvector.psycopg import register_vector
from psycopg_pool import ConnectionPool

from app.config import settings

DEFAULT_TENANT = "default"  # owns all data created before multi-tenancy existed

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
    """Create/upgrade the schema. Safe to run on every startup, on a fresh
    database or on a Phase 1 database that already contains data."""
    # Extension must exist before the pool registers the vector type.
    import psycopg
    with psycopg.connect(settings.database_url, autocommit=True) as conn:
        conn.execute("CREATE EXTENSION IF NOT EXISTS vector")

    dim = settings.embedding_dim
    with connection() as conn:  # one transaction: all of this applies, or none of it
        # --- tenants and their API keys ---
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS tenants (
                id         BIGSERIAL PRIMARY KEY,
                name       TEXT NOT NULL UNIQUE,
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

        # --- documents and chunks (Phase 1 tables) ---
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

        # --- Phase 2 upgrade: every row belongs to a tenant ---
        # (add the column, give old rows to the default tenant, then make it mandatory)
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


# def get_default_tenant_id() -> int:
#     """TEMPORARY (Phase 2, until auth lands in Step 3): the tenant that owns everything."""
#     with connection() as conn:
#         return conn.execute(
#             "SELECT id FROM tenants WHERE name = %s", (DEFAULT_TENANT,)
#         ).fetchone()[0]


def get_tenant_id_for_key_hash(key_hash: str) -> int | None:
    """Tenant that owns an active (non-revoked) key, or None."""
    with connection() as conn:
        row = conn.execute(
            "SELECT tenant_id FROM api_keys WHERE key_hash = %s AND revoked_at IS NULL",
            (key_hash,),
        ).fetchone()
    return row[0] if row else None

def get_tenant_id_by_name(name: str) -> int | None:
    """Used by local scripts (eval); the API never looks tenants up by name."""
    with connection() as conn:
        row = conn.execute("SELECT id FROM tenants WHERE name = %s", (name,)).fetchone()
    return row[0] if row else None

def close_pool() -> None:
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None