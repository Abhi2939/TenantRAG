from app.config import settings
from app.db import connection
from app.embed import embed_query

def retrieve(question: str,k:int | None = None) -> list[dict]:

    k = k or settings.top_k
    q = embed_query(question)

    with connection() as conn:
        rows = conn.execute(
            """
            SELECT c.id, c.document_id, d.source, c.chunk_index, c.text,
                   c.embedding <=> %s::vector AS distance
            FROM chunks c
            JOIN documents d ON d.id = c.document_id
            ORDER BY distance
            LIMIT %s
            """,
            (str(q),k),
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