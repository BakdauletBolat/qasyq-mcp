from datetime import datetime, timedelta

import pytest

from tests.conftest import mcp_call


@pytest.fixture
def auth(tokens):
    return {"Authorization": f"Bearer {tokens['access_token']}"}


def test_weights_require_auth(client):
    assert client.post("/weights", json={"kg": 80}).status_code == 401
    assert client.get("/weights/recent").status_code == 401


def test_weights_recent_window(client, auth):
    old = (datetime.now() - timedelta(days=120)).isoformat()
    client.post("/weights", json={"kg": 90, "recorded_at": old}, headers=auth)
    r = client.post("/weights", json={"kg": 80.5}, headers=auth)
    assert r.status_code == 201 and r.json()["kg"] == 80.5
    rows = client.get("/weights/recent", headers=auth).json()["weights"]
    assert [w["kg"] for w in rows] == [80.5]


def test_weight_validation(client, auth):
    assert client.post("/weights", json={"kg": 0}, headers=auth).status_code == 422
    assert client.post("/weights", json={"kg": 80, "recorded_at": "nope"}, headers=auth).status_code == 422


def test_entries_range(client, auth):
    for d, kcal in (("2026-10-01", 500), ("2026-10-01", 300), ("2026-10-03", 700)):
        client.post(
            "/entries",
            json={"date": d, "name": "x", "grams": 100, "kcal": kcal, "protein": 10, "fat": 5, "carbs": 20},
            headers=auth,
        )
    r = client.get("/entries/range", params={"start": "2026-10-01", "end": "2026-10-31"}, headers=auth).json()
    assert r["days_logged"] == 2
    assert [d["kcal"] for d in r["days"]] == [800, 700]
    assert r["average_per_logged_day"]["kcal"] == 750
    bad = client.get("/entries/range", params={"start": "2026-10-31", "end": "2026-10-01"}, headers=auth)
    assert bad.status_code == 422


def test_mcp_weights_ui(client, tokens):
    tok = tokens["access_token"]
    tools = mcp_call(client, tok, "tools/list").json()["result"]["tools"]
    gw = next(t for t in tools if t["name"] == "get_weights")
    assert gw["_meta"]["ui"]["resourceUri"] == "ui://weights/chart.html"
    assert any(t["name"] == "get_range" for t in tools)
    res = mcp_call(client, tok, "resources/read", {"uri": "ui://weights/chart.html"}).json()["result"]["contents"][0]
    assert res["mimeType"] == "text/html;profile=mcp-app"
    assert "ui/notifications/tool-result" in res["text"]
