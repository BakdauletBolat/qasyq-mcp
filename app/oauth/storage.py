import json
import time
from urllib.parse import urlparse

from app.db import connect
from app.oauth.crypto import new_secret, sha256_hex

CODE_TTL = 60
ACCESS_TTL = 3600
REFRESH_TTL = 30 * 24 * 3600

ALLOWED_REDIRECTS = {"https://claude.ai/api/mcp/auth_callback"}


def redirect_uri_allowed(uri: str) -> bool:
    if uri in ALLOWED_REDIRECTS:
        return True
    p = urlparse(uri)
    return p.scheme == "http" and p.hostname in ("localhost", "127.0.0.1") and not p.fragment


def create_client(db_path: str, redirect_uris: list[str], client_name: str | None) -> dict:
    client_id = new_secret(16)
    now = time.time()
    with connect(db_path) as conn:
        conn.execute(
            "INSERT INTO oauth_clients (client_id, client_name, redirect_uris, created_at) VALUES (?,?,?,?)",
            (client_id, client_name, json.dumps(redirect_uris), now),
        )
    return {"client_id": client_id, "client_id_issued_at": int(now)}


def get_client(db_path: str, client_id: str) -> dict | None:
    with connect(db_path) as conn:
        row = conn.execute("SELECT * FROM oauth_clients WHERE client_id = ?", (client_id,)).fetchone()
    if not row:
        return None
    return {**dict(row), "redirect_uris": json.loads(row["redirect_uris"])}


def create_code(db_path: str, client_id: str, redirect_uri: str, code_challenge: str) -> str:
    code = new_secret()
    with connect(db_path) as conn:
        conn.execute("DELETE FROM oauth_codes WHERE expires_at < ?", (time.time(),))
        conn.execute(
            "INSERT INTO oauth_codes (code_hash, client_id, redirect_uri, code_challenge, expires_at) "
            "VALUES (?,?,?,?,?)",
            (sha256_hex(code), client_id, redirect_uri, code_challenge, time.time() + CODE_TTL),
        )
    return code


def consume_code(db_path: str, code: str) -> dict | None:
    """Atomically marks the code used. On replay, revokes tokens issued from it."""
    code_hash = sha256_hex(code)
    with connect(db_path) as conn:
        row = conn.execute("SELECT * FROM oauth_codes WHERE code_hash = ?", (code_hash,)).fetchone()
        if not row:
            return None
        claimed = conn.execute(
            "UPDATE oauth_codes SET used = 1 WHERE code_hash = ? AND used = 0", (code_hash,)
        ).rowcount
        if not claimed:
            conn.execute("DELETE FROM oauth_tokens WHERE grant_id = ?", (code_hash,))
            return None
        if row["expires_at"] < time.time():
            return None
        return dict(row)


def issue_tokens(db_path: str, client_id: str, grant_id: str) -> dict:
    access, refresh = new_secret(), new_secret()
    now = time.time()
    with connect(db_path) as conn:
        conn.execute("DELETE FROM oauth_tokens WHERE expires_at < ?", (now,))
        conn.executemany(
            "INSERT INTO oauth_tokens (token_hash, kind, client_id, grant_id, expires_at) VALUES (?,?,?,?,?)",
            [
                (sha256_hex(access), "access", client_id, grant_id, now + ACCESS_TTL),
                (sha256_hex(refresh), "refresh", client_id, grant_id, now + REFRESH_TTL),
            ],
        )
    return {
        "access_token": access,
        "token_type": "Bearer",
        "expires_in": ACCESS_TTL,
        "refresh_token": refresh,
    }


def rotate_refresh(db_path: str, refresh_token: str, client_id: str) -> dict | None:
    """Single-use refresh: the whole grant is replaced by a fresh token pair."""
    h = sha256_hex(refresh_token)
    with connect(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM oauth_tokens WHERE token_hash = ? AND kind = 'refresh'", (h,)
        ).fetchone()
        if not row or row["client_id"] != client_id or row["expires_at"] < time.time():
            return None
        deleted = conn.execute("DELETE FROM oauth_tokens WHERE token_hash = ?", (h,)).rowcount
        if not deleted:
            return None
        conn.execute("DELETE FROM oauth_tokens WHERE grant_id = ? AND kind = 'access'", (row["grant_id"],))
        grant_id = row["grant_id"]
    return issue_tokens(db_path, client_id, grant_id)


def verify_access_token(db_path: str, token: str) -> bool:
    with connect(db_path) as conn:
        row = conn.execute(
            "SELECT expires_at FROM oauth_tokens WHERE token_hash = ? AND kind = 'access'",
            (sha256_hex(token),),
        ).fetchone()
    return bool(row) and row["expires_at"] >= time.time()
