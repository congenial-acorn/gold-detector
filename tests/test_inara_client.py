import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import gold_detector.inara_client as inara_client


GOOD_HTML = """
<html><body>
  <a href="/elite/station/111/">Station A</a>
  <a href="/elite/station/222/">Station B</a>
</body></html>
"""


class _FakeResponse:
    def __init__(self, text):
        self.text = text


def test_get_station_market_urls_reports_failed_pages(monkeypatch):
    """When a nearest-stations list page fails to fetch, its URL is reported
    back in the returned failed set so the caller can skip pruning and avoid
    wiping sent_to for stations it could not see this cycle.
    """

    def fake_http_get(url):
        if "failing-url" in url:
            raise ConnectionError("network unreachable")
        return _FakeResponse(GOOD_HTML)

    monkeypatch.setattr(inara_client, "http_get", fake_http_get)

    market_urls, failed = inara_client.get_station_market_urls(
        ["https://good-url", "https://failing-url"]
    )

    assert market_urls == [
        "https://inara.cz/elite/station-market/111/",
        "https://inara.cz/elite/station-market/222/",
    ]
    assert failed == {"https://failing-url"}


def test_get_station_market_urls_no_failures_returns_empty_failed_set(monkeypatch):
    """When all list pages succeed, the failed set is empty (happy path)."""

    def fake_http_get(url):
        return _FakeResponse(GOOD_HTML)

    monkeypatch.setattr(inara_client, "http_get", fake_http_get)

    market_urls, failed = inara_client.get_station_market_urls(
        ["https://good-url-1", "https://good-url-2"]
    )

    assert failed == set()
    assert market_urls == [
        "https://inara.cz/elite/station-market/111/",
        "https://inara.cz/elite/station-market/222/",
    ]
