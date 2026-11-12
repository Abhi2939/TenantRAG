from app.config import settings
from app.db import tenant_connection
from app.embed import embed_query

def retrieve(question: str,*,tenant_id: int, k : int | None = None) -> list[dict]:

    if tenant_id is None: 
        raise ValueError("tenant_id is required")

    k = k or settings.top_k
    q = embed_query(question)

    with tenant_connection(tenant_id) as conn:

        conn.execute("SELECT set_config('hnsw.ef_search', '100', true)")

        rows = conn.execute(
            """
            SELECT c.id, c.document_id, d.source, c.chunk_index, c.text,
                   c.embedding <=> %s::vector AS distance
            FROM chunks c
            JOIN documents d ON d.id = c.document_id
            WHERE c.tenant_id = %s AND d.tenant_id = %s
            ORDER BY distance
            LIMIT %s
            """,
            (str(q),tenant_id,tenant_id,k),
        ).fetchall()

    return [
        {
            "chunk_id": r[0],
            "document_id": r[1],
            "source": r[2],
            "chunk_index": r[3],
            "text": r[4],
            "distance": float(r[5]),
        }

        for r in rows
    ]