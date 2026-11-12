"""Apply the schema and RLS policies as the table owner. Run before deploying new code.

    python -m scripts.migrate

Uses ADMIN_DATABASE_URL (falls back to DATABASE_URL).
"""
from app.db import init_db


def main() -> None:
    init_db()
    print("Schema and policies are up to date.")


if __name__ == "__main__":
    main()