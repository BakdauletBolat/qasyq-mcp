import base64
import hashlib
import re
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.oauth.endpoints import limiter

REDIRECT = "https://claude.ai/api/mcp/auth_callback"
PASSWORD = "s3cret"
VERIFIER = "v" * 50


def challenge_for(verifier: str) -> str:
    return base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()


@pytest.fixture
def settings(tmp_path):
    return Settings(base_url="https://food.test", owner_password=PASSWORD, db_path=str(tmp_path / "t.db"))


@pytest.fixture
def client(settings):
    limiter.reset()
    with TestClient(create_app(settings), base_url="https://food.test") as c:
        yield c


@pytest.fixture
def registered(client):
    r = client.post("/register", json={"redirect_uris": [REDIRECT], "client_name": "claude"})
    assert r.status_code == 201
    return r.json()["client_id"]


def authorize(client, client_id, *, password=PASSWORD, verifier=VERIFIER, redirect_uri=REDIRECT, state="xyz"):
    return client.post(
        "/authorize",
        data={
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "code_challenge": challenge_for(verifier),
            "code_challenge_method": "S256",
            "state": state,
            "password": password,
        },
        follow_redirects=False,
    )


def code_from(resp) -> str:
    assert resp.status_code == 302, resp.text
    return parse_qs(urlparse(resp.headers["location"]).query)["code"][0]


def exchange(client, client_id, code, *, verifier=VERIFIER, redirect_uri=REDIRECT):
    return client.post(
        "/token",
        data={
            "grant_type": "authorization_code",
            "client_id": client_id,
            "code": code,
            "code_verifier": verifier,
            "redirect_uri": redirect_uri,
        },
    )


@pytest.fixture
def tokens(client, registered):
    r = exchange(client, registered, code_from(authorize(client, registered)))
    assert r.status_code == 200, r.text
    return r.json()


MCP_HEADERS = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}


def mcp_call(client, access_token, method, params=None, id=1):
    return client.post(
        "/mcp",
        headers={**MCP_HEADERS, "Authorization": f"Bearer {access_token}"},
        json={"jsonrpc": "2.0", "id": id, "method": method, "params": params or {}},
    )
