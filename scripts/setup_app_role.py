"""Create or refresh the restricted app role and grant it only what the API needs.

    python -m scripts.setup_app_role

Prompts for the role's password (not echoed). Runs the migration first.
Uses ADMIN_DATABASE_URL (falls back to DATABASE_URL).
"""
import getpass
import sys

from psycopg import sql

from app.db import APP_ROLE, admin_connection, init_db


def main() -> None:
    password = getpass.getpass(f"Password for role {APP_ROLE}: ")
    if len(password) < 12:
        sys.exit("Use at least 12 characters (letters and digits keep the URL simple).")

    init_db()  # tables must exist before we grant on them
    role = sql.Identifier(APP_ROLE)
    with admin_connection() as conn:
        exists = conn.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (APP_ROLE,)).fetchone()
        conn.execute(
            sql.SQL("{} ROLE {} LOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE PASSWORD {}").format(
                sql.SQL("ALTER" if exists else "CREATE"), role, sql.Literal(password)
            )
        )
        db = conn.execute("SELECT current_database()").fetchone()[0]
        conn.execute(sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(sql.Identifier(db), role))
        conn.execute(sql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(role))
        conn.execute(sql.SQL("GRANT SELECT, INSERT ON documents, chunks TO {}").format(role))
        conn.execute(
            sql.SQL("GRANT USAGE, SELECT ON SEQUENCE documents_id_seq, chunks_id_seq TO {}").format(role)
        )
        conn.execute(sql.SQL("GRANT SELECT (key_hash, tenant_id, revoked_at) ON api_keys TO {}").format(role))

        # Where does the vector type live? (public locally, often `extensions` on Supabase)
        ext_schema = conn.execute(
            "SELECT n.nspname FROM pg_extension e JOIN pg_namespace n ON n.oid = e.extnamespace "
            "WHERE e.extname = 'vector'"
        ).fetchone()[0]
        schemas = ["public"] + ([ext_schema] if ext_schema != "public" else [])
        if ext_schema != "public":
            conn.execute(sql.SQL("GRANT USAGE ON SCHEMA {} TO {}").format(sql.Identifier(ext_schema), role))
        conn.execute(
            sql.SQL("ALTER ROLE {} SET search_path = {}").format(
                role, sql.SQL(", ").join(sql.Identifier(s) for s in schemas)
            )
        )
    print(f"Role {APP_ROLE} is ready.")


if __name__ == "__main__":
    main()