from fastapi.testclient import TestClient

from filings_hub.api.app import create_app
from filings_hub.config import Settings


def test_watchlist_rejects_account_switch_and_uses_company_directory(lake_copy):
    app = create_app(
        Settings(lake_root=lake_copy.root, database_url="", api_key="k", sec_user_agent="", _env_file=None)
    )
    try:
        a = app.state.users.create_user("a@example.com")
        b = app.state.users.create_user("b@example.com")
        ha = {"X-API-Key": "k", "X-Session": app.state.signer.sign(a.id)}
        hb = {"X-API-Key": "k", "X-Session": app.state.signer.sign(b.id)}
        with TestClient(app) as client:
            payload = {"expected_user_id": a.id, "action": "toggle", "cik": 320193, "name": "Spoofed name"}
            result = client.post("/me/watchlist", json=payload, headers=ha)
            assert result.status_code == 200, result.text
            assert result.json()["followed"] is True
            assert result.json()["companies"][0]["name"] != "Spoofed name"
            assert client.post("/me/watchlist", json=payload, headers=hb).status_code == 409
            assert client.get("/me/watchlist", headers=hb).json()["companies"] == []
            assert client.post("/me/watchlist", json=payload, headers=ha).json()["followed"] is False
            assert client.get("/me/watchlist", headers=ha).json()["companies"] == []
    finally:
        app.state.db.close()
