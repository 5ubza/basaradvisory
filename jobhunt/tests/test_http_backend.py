import json

import requests

from jobhunt.http import PoliteSession


class _Resp:
    def __init__(self, status, payload=None, text=""):
        self.status_code = status
        self._payload = payload
        self.text = text or (json.dumps(payload) if payload is not None else "")

    def json(self):
        return self._payload


def test_firecrawl_backend_is_used_for_proxied_hosts(monkeypatch):
    monkeypatch.setenv("FIRECRAWL_API_KEY", "x")
    monkeypatch.delenv("BRIGHTDATA_API_KEY", raising=False)
    calls = []

    def fake_post(url, headers=None, json=None, timeout=None):
        calls.append((url, json["url"]))
        return _Resp(200, {"success": True, "data": {"rawHtml": "<html>ok</html>", "metadata": {"statusCode": 200}}})

    http = PoliteSession(min_delay=0, proxied_hosts=["bayt.com"], backend="auto")
    assert http.backend == "firecrawl"
    monkeypatch.setattr(http.s, "post", fake_post)
    monkeypatch.setattr(http.s, "get", lambda *a, **k: (_ for _ in ()).throw(AssertionError("direct GET must not happen")))
    r = http.get("https://www.bayt.com/en/qatar/jobs/economist-jobs/")
    assert r is not None and r.text == "<html>ok</html>" and calls[0][0].startswith("https://api.firecrawl.dev/v2/scrape")


def test_backend_failure_counts_towards_host_budget(monkeypatch):
    monkeypatch.setenv("FIRECRAWL_API_KEY", "x")
    http = PoliteSession(min_delay=0, proxied_hosts=["gulftalent.com"], backend="firecrawl", host_failure_budget=2)
    monkeypatch.setattr(http.s, "post", lambda *a, **k: _Resp(402, text="insufficient_credits"))
    assert http.get("https://www.gulftalent.com/qatar/jobs/title/economist") is None
    assert http.get("https://www.gulftalent.com/qatar/jobs/title/policy-analyst") is None
    assert "www.gulftalent.com" in http._dead_hosts


def test_no_backend_goes_direct_and_gives_up_fast(monkeypatch):
    monkeypatch.delenv("FIRECRAWL_API_KEY", raising=False)
    monkeypatch.delenv("BRIGHTDATA_API_KEY", raising=False)
    http = PoliteSession(min_delay=0, proxied_hosts=["bayt.com"], respect_robots=False, host_failure_budget=1)
    assert http.backend is None

    def boom(*a, **k):
        raise requests.ReadTimeout("stalled")

    monkeypatch.setattr(http.s, "get", boom)
    assert http.get("https://www.bayt.com/en/qatar/jobs/economist-jobs/", retries=0) is None
    assert http.get("https://www.bayt.com/en/qatar/jobs/policy-analyst-jobs/", retries=0) is None  # skipped, host dead
