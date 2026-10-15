import json
import threading
from http.server import ThreadingHTTPServer

import httpx
import pytest

from fantasy.app import FantasyApp
from fantasy.config import load_config
from fantasy.web.server import make_handler


@pytest.fixture
def server(tmp_path):
    config = load_config({"FANTASY_DATA_DIR": str(tmp_path)})
    app = FantasyApp(config, demo=True)
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), lambda *a: None)  # placeholder handler
    port = httpd.server_address[1]
    httpd.RequestHandlerClass = make_handler(app, {f"127.0.0.1:{port}", f"localhost:{port}"})
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{port}"
    httpd.shutdown()
    httpd.server_close()


def test_dashboard_refresh_and_report(server):
    page = httpx.get(server + "/")
    assert page.status_code == 200 and "COPY DAILY FANTASY REPORT" in page.text
    assert "Download .md" in page.text
    assert httpx.get(server + "/static/app.js").status_code == 200
    assert httpx.get(server + "/static/../config.py").status_code == 404

    assert httpx.get(server + "/api/state").json() == {"view": None, "demo": True}
    assert httpx.get(server + "/api/report").status_code == 404

    refreshed = httpx.post(server + "/api/refresh", timeout=60)
    assert refreshed.status_code == 200
    view = refreshed.json()["view"]
    assert view["meta"]["my_team"] == "Rembates Hektors IR"
    assert view["changes"]["since"] is not None  # demo writes yesterday's snapshot too

    report = httpx.get(server + "/api/report")
    assert report.headers["content-type"].startswith("text/plain")
    assert report.text.startswith("# DAILY FANTASY REPORT")
    compact = httpx.get(server + "/api/report?compact=1")
    assert len(compact.text) < len(report.text)
    json.loads(httpx.get(server + "/api/state").text)  # strict JSON, no NaN


def test_foreign_hosts_and_cross_site_posts_are_refused(server):
    assert httpx.get(server + "/api/state", headers={"Host": "evil.example"}).status_code == 403
    response = httpx.post(server + "/api/refresh", headers={"Origin": "https://evil.example"})
    assert response.status_code == 403


def test_live_refresh_without_league_id_reports_the_setting(tmp_path):
    config = load_config({"FANTASY_DATA_DIR": str(tmp_path)})
    app = FantasyApp(config)
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), lambda *a: None)
    port = httpd.server_address[1]
    httpd.RequestHandlerClass = make_handler(app, {f"127.0.0.1:{port}"})
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        response = httpx.post(f"http://127.0.0.1:{port}/api/refresh")
        assert response.status_code == 400
        assert "ESPN_LEAGUE_ID" in response.json()["error"]
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_settings_endpoint_never_returns_cookies(server, tmp_path, monkeypatch):
    from fantasy.config import SETTINGS_KEYS

    for key in SETTINGS_KEYS:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr("fantasy.config.PROJECT_DIR", tmp_path)
    assert httpx.get(server + "/api/settings").json()["has_espn_s2"] is False
    response = httpx.post(
        server + "/api/settings",
        json={
            "league_url": "https://fantasy.espn.com/basketball/team?leagueId=42&teamId=1",
            "espn_s2": "secret-cookie",
        },
    )
    assert response.status_code == 200
    assert response.json()["settings"]["league_id"] == 42
    assert "secret-cookie" not in response.text
    assert "secret-cookie" not in httpx.get(server + "/api/settings").text
    bad = httpx.post(server + "/api/settings", json={"punt": "DUNKS"})
    assert bad.status_code == 400 and "FANTASY_PUNT" in bad.json()["error"]


def test_trade_endpoint(server):
    view = httpx.post(server + "/api/refresh", timeout=60).json()["view"]
    give = [view["my_team"]["roster"][-2]["id"]]
    partner = next(t for t in view["teams"] if not t["is_me"])
    get = [partner["roster"][0]["id"]]
    response = httpx.post(server + "/api/trade", json={"give": give, "get": get})
    assert response.status_code == 200 and response.json()["partner"] == partner["name"]
    bad = httpx.post(server + "/api/trade", json={"give": get, "get": give})
    assert bad.status_code == 400 and "own roster" in bad.json()["error"]


def test_demo_refresh_fills_the_accuracy_log(server):
    view = httpx.post(server + "/api/refresh", timeout=60).json()["view"]
    assert view["accuracy"]["matchups"] == 1
    assert view["accuracy"]["forecasts"] == 9
