"""Load documents, chunk them, embed chunks, store in pgvector."""
import io

from app.chunking import chunk_text
from app.config import settings
from app.db import connection
from app.embed import embed_documents

SUPPORTED = (".txt", ".md", ".pdf")

def load_text(filename: str, data: bytes) -> str:
    name = filename.lower()
    if name.endswith((".txt", ".md")):
        return data.decode("utf-8", errors="replace")
    if name.endswith(".pdf"):
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(data))
        return "\n".join((page.extract_text() or "") for page in reader.pages)
    raise ValueError(f"Unsupported file type: {filename}. Use one of {SUPPORTED}")


def ingest_document(source: str, text: str, tenant_id: int) -> tuple[int, int]:
    """Chunk, embed and store one document. Returns (document_id, n_chunks)."""

    chunks = chunk_text(text, settings.chunk_size, settings.chunk_overlap)
    if not chunks:
        raise ValueError("Document has no extractable text")

    vectors = embed_documents(chunks)

    # One transaction: a document is either fully stored or not at all.
    with connection() as conn:
        doc_id = conn.execute(
            "INSERT INTO documents (source, tenant_id) VALUES (%s, %s) RETURNING id",
            (source, tenant_id),
        ).fetchone()[0]
        with conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO chunks (document_id, tenant_id, chunk_index, text, embedding) "
                "VALUES (%s, %s, %s, %s, %s)",
                [(doc_id, tenant_id, i, c, v) for i, (c, v) in enumerate(zip(chunks, vectors))],
            )
    return doc_id, len(chunks)