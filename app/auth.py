from fastapi import Depends,HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.db import get_tenant_id_for_key_hash
from app.keys import KEY_TAG,hash_key


_bearer = HTTPBearer(auto_error=False)

def _unauthorized() -> HTTPException:
    
    return HTTPException(
        status_code=401,
        detail="Invalid or missing API key",
        headers={"WWW-Authenticate": "Bearer"},
    )

def require_tenant(creds: HTTPAuthorizationCredentials | None = Depends(_bearer)) -> int:

    if creds is None or not creds.credentials.startswith(KEY_TAG):
        raise _unauthorized()  
    tenant_id = get_tenant_id_for_key_hash(hash_key(creds.credentials))
    if tenant_id is None:
        raise _unauthorized() 
    return tenant_id

