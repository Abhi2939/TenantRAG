import psycopg
from app.config import settings

with psycopg.connect(settings.database_url) as conn:
    print(conn.execute("select version()").fetchone()[0])
    print(conn.execute("select count(*) from pg_available_extensions where name = 'vector'").fetchone())