"""Cross-tenant leak tests: the main deliverable of Phase 2.

App level:      retrieve() and the API only ever return the caller's own chunks.
Database level: Postgres enforces isolation by itself, as the restricted app role.

Runs against the LOCAL Docker database only. Creates two throwaway tenants and
deletes them (cascading to their documents, chunks and keys) at the end.
"""
import uuid
from types import SimpleNamespace
from urllib.parse import urlparse

import psycopg
import pytest
from fastapi.testclient import TestClient

import app.main as main_mod
from app.config import settings
from app.db import admin_connection, close_pool, connection, tenant_connection
from app.ingest import ingest_document
from app.keys import generate_key, hash_key, key_prefix
from app.retrieve import retrieve

DOC_A = (
    "Alpha Corp vault policy. The vault access code is ALPHA-7731. "
    "Alpha Corp stores its backups in Mumbai."
)
DOC_B = (
    "Bravo Ltd vault policy. The vault access code is BRAVO-4482. "
    "Bravo Ltd stores its backups in Oslo."
)
SHARED_QUESTIONS = [
    "What is the vault access code?",
    "Where are the backups stored?",
    "Tell me about the vault policy.",
]


@pytest.fixture(scope="module", autouse=True)
def _local_only():
    for url in (settings.database_url, settings.admin_database_url or settings.database_url):
        if urlparse(url).hostname not in ("localhost", "127.0.0.1"):
            pytest.fail("Leak tests run against the local database only.", pytrace=False)


def _make_tenant(label: str, text: str):
    name = f"leaktest-{label}-{uuid.uuid4().hex[:8]}"
    key = generate_key()
    with admin_connection() as conn:
        tid = conn.execute(
            "INSERT INTO tenants (name) VALUES (%s) RETURNING id", (name,)
        ).fetchone()[0]
        conn.execute(
            "INSERT INTO api_keys (tenant_id, key_hash, key_prefix) VALUES (%s, %s, %s)",
            (tid, hash_key(key), key_prefix(key)),
        )
    doc_id, _ = ingest_document(f"{label}-vault.md", text, tenant_id=tid)
    return SimpleNamespace(id=tid, name=name, key=key, doc_ids={doc_id})


@pytest.fixture(scope="module")
def tenants(_local_only):
    a = _make_tenant("a", DOC_A)
    b = _make_tenant("b", DOC_B)
    yield a, b
    with admin_connection() as conn:  # cascades to api_keys, documents, chunks
        conn.execute("DELETE FROM tenants WHERE id IN (%s, %s)", (a.id, b.id))
    close_pool()


@pytest.fixture
def client(monkeypatch):
    # Exercise the real route + auth + retrieve wiring, without calling the LLM.
    monkeypatch.setattr(main_mod, "generate", lambda question, chunks: "stub answer")
    return TestClient(main_mod.app)


def _bearer(t):
    return {"Authorization": f"Bearer {t.key}"}


def _text(chunks):
    return " ".join(c["text"] for c in chunks)


# ---------------- app level ----------------

def test_retrieve_returns_only_own_chunks(tenants):
    a, b = tenants
    for me, other in ((a, b), (b, a)):
        for q in SHARED_QUESTIONS:
            chunks = retrieve(q, tenant_id=me.id, k=10)
            assert chunks, "tenant should find its own data"
            assert all(c["document_id"] in me.doc_ids for c in chunks)
            assert not any(c["document_id"] in other.doc_ids for c in chunks)


def test_same_question_gives_each_tenant_its_own_answer_source(tenants):
    a, b = tenants
    q = "What is the vault access code?"
    text_a = _text(retrieve(q, tenant_id=a.id, k=10))
    text_b = _text(retrieve(q, tenant_id=b.id, k=10))
    assert "ALPHA-7731" in text_a and "BRAVO-4482" not in text_a
    assert "BRAVO-4482" in text_b and "ALPHA-7731" not in text_b


def test_searching_for_the_other_tenants_secret_finds_nothing(tenants):
    a, b = tenants
    assert "BRAVO-4482" not in _text(retrieve("BRAVO-4482 Bravo Ltd Oslo", tenant_id=a.id, k=10))
    assert "ALPHA-7731" not in _text(retrieve("ALPHA-7731 Alpha Corp Mumbai", tenant_id=b.id, k=10))


def test_retrieve_fails_closed_without_a_tenant():
    with pytest.raises(ValueError):
        retrieve("anything", tenant_id=None)


def test_api_query_is_scoped_by_key(tenants, client):
    a, b = tenants
    for me, other in ((a, b), (b, a)):
        r = client.post(
            "/query",
            json={"question": "What is the vault access code?", "top_k": 10},
            headers=_bearer(me),
        )
        assert r.status_code == 200
        sources = r.json()["sources"]
        assert sources
        assert all(s["document_id"] in me.doc_ids for s in sources)
        assert not any(s["document_id"] in other.doc_ids for s in sources)


def test_document_ingested_through_api_is_invisible_to_other_tenant(tenants, client):
    a, b = tenants
    r = client.post(
        "/ingest",
        files={"file": ("a-extra.md", b"The launch codename is ZULU-9090.", "text/markdown")},
        headers=_bearer(a),
    )
    assert r.status_code == 200
    extra_doc = r.json()["document_id"]
    a.doc_ids.add(extra_doc)

    mine = client.post("/query", json={"question": "launch codename ZULU-9090", "top_k": 10}, headers=_bearer(a))
    theirs = client.post("/query", json={"question": "launch codename ZULU-9090", "top_k": 10}, headers=_bearer(b))
    assert any("ZULU-9090" in s["text"] for s in mine.json()["sources"])
    assert not any("ZULU-9090" in s["text"] for s in theirs.json()["sources"])


# ---------------- database level (connected as the restricted app role) ----------------

def test_app_connection_really_is_restricted():
    with connection() as conn:
        sup, byp = conn.execute(
            "SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user"
        ).fetchone()
        owner_is_me = conn.execute(
            "SELECT count(*) FROM pg_tables WHERE tablename IN ('documents','chunks') "
            "AND tableowner = current_user"
        ).fetchone()[0]
    assert not sup and not byp, "app role must not bypass RLS"
    assert owner_is_me == 0, "app role must not own the tenant tables"


def test_no_tenant_set_returns_zero_rows(tenants):
    a, b = tenants
    with admin_connection() as conn:  # sanity: the rows exist
        assert conn.execute(
            "SELECT count(*) FROM documents WHERE tenant_id IN (%s, %s)", (a.id, b.id)
        ).fetchone()[0] >= 2
    with connection() as conn:
        assert conn.execute("SELECT count(*) FROM documents").fetchone()[0] == 0
        assert conn.execute("SELECT count(*) FROM chunks").fetchone()[0] == 0


def test_tenant_context_sees_only_its_own_rows(tenants):
    a, b = tenants
    with tenant_connection(a.id) as conn:
        assert conn.execute("SELECT DISTINCT tenant_id FROM documents").fetchall() == [(a.id,)]
        assert conn.execute("SELECT DISTINCT tenant_id FROM chunks").fetchall() == [(a.id,)]
        # asking for the other tenant's rows explicitly still returns nothing
        assert conn.execute("SELECT count(*) FROM chunks WHERE tenant_id = %s", (b.id,)).fetchone()[0] == 0
        assert conn.execute("SELECT count(*) FROM documents WHERE tenant_id = %s", (b.id,)).fetchone()[0] == 0


def test_cannot_insert_a_document_for_another_tenant(tenants):
    a, b = tenants
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        with tenant_connection(a.id) as conn:
            conn.execute("INSERT INTO documents (source, tenant_id) VALUES ('evil', %s)", (b.id,))


def test_cannot_insert_a_chunk_for_another_tenant(tenants):
    a, b = tenants
    vec = str([0.0] * settings.embedding_dim)
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        with tenant_connection(a.id) as conn:
            conn.execute(
                "INSERT INTO chunks (document_id, tenant_id, chunk_index, text, embedding) "
                "VALUES (%s, %s, 0, 'evil', %s::vector)",
                (next(iter(a.doc_ids)), b.id, vec),
            )


def test_cannot_write_without_a_tenant(tenants):
    a, _ = tenants
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        with connection() as conn:
            conn.execute("INSERT INTO documents (source, tenant_id) VALUES ('evil', %s)", (a.id,))


def test_tenant_setting_does_not_leak_into_the_next_transaction(tenants):
    a, _ = tenants
    with tenant_connection(a.id) as conn:
        assert conn.execute("SELECT count(*) FROM documents").fetchone()[0] >= 1
    with connection() as conn:  # pooled connection, reused: must be back to "no tenant"
        assert conn.execute("SELECT count(*) FROM documents").fetchone()[0] == 0


def test_app_role_cannot_read_tenants_or_key_metadata():
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        with connection() as conn:
            conn.execute("SELECT * FROM tenants")
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        with connection() as conn:
            conn.execute("SELECT key_prefix FROM api_keys")