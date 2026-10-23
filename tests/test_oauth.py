import json
import sqlite3
from urllib.parse import parse_qs, urlparse

from app.oauth import endpoints
from tests.conftest import (
    PASSWORD,
    REDIRECT,
    VERIFIER,
    authorize,
    challenge_for,
    code_from,
    exchange,
    mcp_call,
)

INIT = {
    "protocolVersion": "2025-06-18",
    "capabilities": {},
    "clientInfo": {"name": "t", "version": "0"},
}


def test_metadata(client):
    pr = client.get("/.well-known/oauth-protected-resource").json()
    assert pr["resource"] == "https://food.test/mcp"
    assert pr["authorization_servers"] == ["https://food.test"]
    as_ = client.get("/.well-known/oauth-authorization-server").json()
    assert as_["code_challenge_methods_supported"] == ["S256"]
    assert as_["registration_endpoint"] == "https://food.test/register"


def test_full_flow_to_mcp(client, registered):
    r = authorize(client, registered)
    assert parse_qs(urlparse(r.headers["location"]).query)["state"] == ["xyz"]
    tok = exchange(client, registered, code_from(r)).json()
    assert tok["token_type"] == "Bearer" and tok["expires_in"] == 3600 and tok["refresh_token"]

    at = tok["access_token"]
    assert mcp_call(client, at, "initialize", INIT).status_code == 200

    def call(name, args, id):
        r = mcp_call(client, at, "tools/call", {"name": name, "arguments": args}, id=id)
        assert r.status_code == 200, r.text
        res = r.json()["result"]
        assert not res.get("isError"), res
        return json.loads(res["content"][0]["text"])

    call("log_entry", {"date": "2026-01-02", "name": "oats", "grams": 80, "kcal": 300,
                       "protein": 10, "fat": 6, "carbs": 50}, 2)
    day = call("get_day", {"date": "2026-01-02"}, 3)
    assert day["totals"]["kcal"] == 300 and len(day["entries"]) == 1
    entry_id = day["entries"][0]["id"]
    call("delete_entry", {"entry_id": entry_id}, 4)
    assert call("get_day", {"date": "2026-01-02"}, 5)["entries"] == []


def test_mcp_and_rest_require_bearer(client, tokens):
    for resp in (
        client.post("/mcp", json={}),
        client.get("/entries", params={"date": "2026-01-01"}),
        client.get("/entries", params={"date": "2026-01-01"}, headers={"Authorization": "Bearer nope"}),
    ):
        assert resp.status_code == 401
        assert resp.headers["www-authenticate"] == (
            'Bearer resource_metadata="https://food.test/.well-known/oauth-protected-resource"'
        )
    ok = client.get("/entries", params={"date": "2026-01-01"},
                    headers={"Authorization": f"Bearer {tokens['access_token']}"})
    assert ok.status_code == 200


def test_pkce_wrong_verifier(client, registered):
    code = code_from(authorize(client, registered))
    r = exchange(client, registered, code, verifier="w" * 50)
    assert r.status_code == 400 and r.json()["error"] == "invalid_grant"


def test_code_is_single_use_and_replay_revokes(client, registered):
    code = code_from(authorize(client, registered))
    first = exchange(client, registered, code)
    assert first.status_code == 200
    assert exchange(client, registered, code).status_code == 400
    # tokens issued from the replayed code are revoked
    r = client.get("/entries", params={"date": "2026-01-01"},
                   headers={"Authorization": f"Bearer {first.json()['access_token']}"})
    assert r.status_code == 401


def test_code_expires(client, registered, settings):
    code = code_from(authorize(client, registered))
    with sqlite3.connect(settings.db_path) as c:
        c.execute("UPDATE oauth_codes SET expires_at = 0")
    assert exchange(client, registered, code).status_code == 400


def test_expired_access_token(client, tokens, settings):
    with sqlite3.connect(settings.db_path) as c:
        c.execute("UPDATE oauth_tokens SET expires_at = 0 WHERE kind = 'access'")
    r = client.post("/mcp", headers={"Authorization": f"Bearer {tokens['access_token']}"}, json={})
    assert r.status_code == 401


def test_refresh_rotation(client, registered, tokens):
    r = client.post("/token", data={"grant_type": "refresh_token", "client_id": registered,
                                    "refresh_token": tokens["refresh_token"]})
    assert r.status_code == 200
    new = r.json()
    assert new["refresh_token"] != tokens["refresh_token"]
    # old refresh and old access are dead, new access works
    again = client.post("/token", data={"grant_type": "refresh_token", "client_id": registered,
                                        "refresh_token": tokens["refresh_token"]})
    assert again.status_code == 400
    h = lambda t: {"Authorization": f"Bearer {t}"}
    q = {"date": "2026-01-01"}
    assert client.get("/entries", params=q, headers=h(tokens["access_token"])).status_code == 401
    assert client.get("/entries", params=q, headers=h(new["access_token"])).status_code == 200


def test_tokens_stored_hashed(client, tokens, settings):
    with sqlite3.connect(settings.db_path) as c:
        hashes = {r[0] for r in c.execute("SELECT token_hash FROM oauth_tokens")}
    assert tokens["access_token"] not in hashes and tokens["refresh_token"] not in hashes
    assert all(len(h) == 64 for h in hashes)


def test_register_rejects_foreign_redirect(client):
    r = client.post("/register", json={"redirect_uris": ["https://evil.example/cb"]})
    assert r.status_code == 400 and r.json()["error"] == "invalid_redirect_uri"
    ok = client.post("/register", json={"redirect_uris": ["http://localhost:6274/callback"]})
    assert ok.status_code == 201


def test_authorize_unregistered_redirect_uri(client, registered):
    r = authorize(client, registered, redirect_uri="https://evil.example/cb")
    assert r.status_code == 400 and "location" not in r.headers


def test_authorize_requires_pkce_and_password(client, registered):
    r = client.get("/authorize", params={
        "response_type": "code", "client_id": registered, "redirect_uri": REDIRECT, "state": "s"},
        follow_redirects=False)
    assert r.status_code == 302 and "error=invalid_request" in r.headers["location"]

    bad = authorize(client, registered, password="wrong")
    assert bad.status_code == 401 and "location" not in bad.headers
    assert authorize(client, registered).status_code == 302


def test_token_redirect_uri_mismatch(client, registered):
    code = code_from(authorize(client, registered))
    r = exchange(client, registered, code, redirect_uri="http://localhost/cb")
    assert r.status_code == 400


def test_authorize_rate_limited(client, registered):
    limit = endpoints.AUTHORIZE_PER_IP[0]
    codes = [authorize(client, registered, password="bad").status_code for _ in range(limit + 2)]
    assert codes[:limit] == [401] * limit and codes[limit:] == [429, 429]
    # even the right password is blocked while limited
    assert authorize(client, registered).status_code == 429


def test_token_rate_limited(client, registered):
    limit = endpoints.TOKEN_PER_IP[0]
    statuses = [exchange(client, registered, "bogus").status_code for _ in range(limit + 1)]
    assert statuses[-1] == 429
