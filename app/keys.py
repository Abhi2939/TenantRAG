import hashlib
import secrets

KEY_TAG = "trag_"

def generate_key() -> str:
    return KEY_TAG + secrets.token_urlsafe(32)

def hash_key(key:str) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest()

def key_prefix(key:str) -> str:
    return key[:8]