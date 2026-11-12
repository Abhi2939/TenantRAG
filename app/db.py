"""Postgres + pgvector. The ONLY module that talks to the DB driver.

Two kinds of connection:
- App connections (DATABASE_URL, restricted role). Row-level security applies, so
  tenant_connection() must set the tenant before touching tenant tables.
- Admin connections (ADMIN_DATABASE_URL, table owner). Migrations and local scripts only.
"""
from contextlib import contextmanager

import psycopg
from pgvector.psycopg import register_vector
from psycopg_pool import ConnectionPool

from app.config import settings

DEFAULT_TENANT = "default"  # owns all data created before multi-tenancy existed
APP_ROLE = "tenantrag_app"  # restricted role the API connects as

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
    """App connection with NO tenant set: RLS-protected tenant tables return zero rows."""
    with get_pool().connection() as conn:
        yield conn


@contextmanager
def tenant_connection(tenant_id: int):
    """App connection scoped to one tenant for this transaction only (is_local = true)."""
    if tenant_id is None:
        raise ValueError("tenant_id is required")
    with get_pool().connection() as conn:
        conn.execute("SELECT set_config('app.tenant_id', %s, true)", (str(int(tenant_id)),))
        yield conn


def admin_connection():
    """Owner connection for migrations and local scripts. Use as a context manager."""
    return psycopg.connect(settings.admin_database_url or settings.database_url)


def init_db() -> None:
    """Create/upgrade the schema and RLS policies. Safe to run repeatedly, on a fresh
    database or on one that already contains data. Needs the admin (owner) connection:
    the restricted app role cannot alter tables."""
    admin_url = settings.admin_database_url or settings.database_url
    # Extension must exist before anything registers the vector type.
    with psycopg.connect(admin_url, autocommit=True) as conn:
        conn.execute("CREATE EXTENSION IF NOT EXISTS vector")

    dim = settings.embedding_dim
    with admin_connection() as conn:  # one transaction: all of this applies, or none of it
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

        # --- Row-level security: a row is visible only to its own tenant ---
        # No tenant set -> nullif gives NULL -> comparison is never true -> zero rows (fail closed).
        for table in ("documents", "chunks"):
            conn.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
            conn.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
            conn.execute(
                f"""
                CREATE POLICY tenant_isolation ON {table}
                    USING      (tenant_id = nullif(current_setting('app.tenant_id', true), '')::bigint)
                    WITH CHECK (tenant_id = nullif(current_setting('app.tenant_id', true), '')::bigint)
                """
            )

        # tenants / api_keys: RLS on with no general policy hides them from every role except
        # the owner. The API's login gets one narrow policy so the key lookup still works.
        for table in ("tenants", "api_keys"):
            conn.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        conn.execute("DROP POLICY IF EXISTS app_key_lookup ON api_keys")
        conn.execute(
            f"CREATE POLICY app_key_lookup ON api_keys FOR SELECT "
            f"USING (current_user = '{APP_ROLE}')"
        )


def get_tenant_id_for_key_hash(key_hash: str) -> int | None:
    """Tenant that owns an active (non-revoked) key, or None."""
    with connection() as conn:
        row = conn.execute(
            "SELECT tenant_id FROM api_keys WHERE key_hash = %s AND revoked_at IS NULL",
            (key_hash,),
        ).fetchone()
    return row[0] if row else None


def get_tenant_id_by_name(name: str) -> int | None:
    """For local scripts (eval). Admin connection: the app role cannot read `tenants`."""
    with admin_connection() as conn:
        row = conn.execute("SELECT id FROM tenants WHERE name = %s", (name,)).fetchone()
    return row[0] if row else None


def close_pool() -> None:
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None