import base64
import hashlib
import hmac
import re
import secrets

_VERIFIER_RE = re.compile(r"^[A-Za-z0-9\-._~]{43,128}$")


def sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def new_secret(nbytes: int = 32) -> str:
    return secrets.token_urlsafe(nbytes)


def pkce_s256(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode()).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


def verify_pkce(verifier: str, challenge: str) -> bool:
    if not _VERIFIER_RE.match(verifier):
        return False
    return hmac.compare_digest(pkce_s256(verifier), challenge)


def constant_time_eq(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode(), b.encode())
