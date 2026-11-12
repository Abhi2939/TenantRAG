import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

import app.auth as auth
from app.keys import generate_key, hash_key

GOOD = generate_key()
REVOKED = generate_key()


@pytest.fixture
def client(monkeypatch):
    def fake_lookup(h):
        return 7 if h == hash_key(GOOD) else None  

    monkeypatch.setattr(auth, "get_tenant_id_for_key_hash", fake_lookup)
    app = FastAPI()

    @app.get("/who")
    def who(tenant_id: int = Depends(auth.require_tenant)):
        return {"tenant_id": tenant_id}

    return TestClient(app)


def test_valid_key_returns_tenant(client):
    r = client.get("/who", headers={"Authorization": f"Bearer {GOOD}"})
    assert r.status_code == 200 and r.json() == {"tenant_id": 7}


@pytest.mark.parametrize("headers", [
    {},                                          
    {"Authorization": "Bearer"},                 
    {"Authorization": f"Basic {GOOD}"},          
    {"Authorization": "Bearer not_a_trag_key"},  
    {"Authorization": f"Bearer {generate_key()}"},  
    {"Authorization": f"Bearer {REVOKED}"},      
])
def test_bad_keys_get_401(client, headers):
    r = client.get("/who", headers=headers)
    assert r.status_code == 401
    assert r.headers["WWW-Authenticate"] == "Bearer"