
import argparse
import sys

import psycopg

from app.db import close_pool, admin_connection, init_db
from app.keys import generate_key, hash_key, key_prefix


def create_key_for(name: str, existing: bool) -> tuple[int, str]:
    """Returns (tenant_id, plain_key). Raises ValueError for user mistakes."""
    key = generate_key()
    try:
        with admin_connection() as conn:  # one transaction: tenant + key together, or neither
            row = conn.execute("SELECT id FROM tenants WHERE name = %s", (name,)).fetchone()
            if existing:
                if row is None:
                    raise ValueError(f"No tenant named {name!r}. Drop --existing to create it.")
                tenant_id = row[0]
            else:
                if row is not None:
                    raise ValueError(f"Tenant {name!r} already exists. Use --existing to add another key.")
                tenant_id = conn.execute(
                    "INSERT INTO tenants (name) VALUES (%s) RETURNING id", (name,)
                ).fetchone()[0]
            conn.execute(
                "INSERT INTO api_keys (tenant_id, key_hash, key_prefix) VALUES (%s, %s, %s)",
                (tenant_id, hash_key(key), key_prefix(key)),
            )
    except psycopg.errors.UniqueViolation:
        raise ValueError(f"Tenant {name!r} was created at the same moment by someone else. Try again.")
    return tenant_id, key


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("name")
    p.add_argument("--existing", action="store_true")
    args = p.parse_args()

    name = args.name.strip()
    if not name:
        sys.exit("Tenant name cannot be empty.")

    init_db()
    try:
        tenant_id, key = create_key_for(name, args.existing)
    except ValueError as e:
        sys.exit(str(e))
    finally:
        close_pool()

    print(f"\nTenant: {name} (id {tenant_id})")
    print(f"API key: {key}")
    print("\nCopy it now. It is stored only as a hash and cannot be shown again.\n")


if __name__ == "__main__":
    main()