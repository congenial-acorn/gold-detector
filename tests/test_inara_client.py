import sys
from pathlib import Path

import pytest
from bs4 import BeautifulSoup

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import gold_detector.inara_client as inara_client


def _station_page(minor_faction_value: str) -> BeautifulSoup:
    return BeautifulSoup(
        f"""
        <div class="itempaircontainer">
          <div class="itempairlabel">Landing pad</div>
          <div class="itempairvalue">Large</div>
        </div>
        <div class="itempaircontainer">
          <div class="itempairlabel">Minor faction</div>
          <div class="itempairvalue">{minor_faction_value}</div>
        </div>
        """,
        "html.parser",
    )


SYSTEM_FACTIONS_HTML = """
<h2>System minor factions</h2>
<table class="tablesorter">
  <thead><tr>
    <th>Faction</th><th>Government</th><th>Allegiance</th>
    <th>Pending</th><th>Active</th><th>Inf</th>
  </tr></thead>
  <tbody>
    <tr>
      <td><a href="/elite/minorfaction/76647/">Olympus Trading Corp</a>
        <span class="tag taginline minor">Player</span></td>
      <td>Corporate</td><td>Federation</td>
      <td class="wrap minor"><span class="statetag statetag1">Expansion</span></td>
      <td class="wrap"><span class="statetag statetag26">Infrastructure failure</span></td>
      <td>71.4%</td>
    </tr>
    <tr>
      <td><a href="/elite/minorfaction/77190/">Independent Pilot's Guild</a></td>
      <td>Theocracy</td><td>Independent</td>
      <td class="wrap minor"></td><td class="wrap"></td><td>19.7%</td>
    </tr>
  </tbody>
</table>
"""


def test_parse_station_owner_reads_minor_faction_link():
    owner = inara_client.parse_station_owner(
        _station_page('<a href="/elite/minorfaction/76647/">Olympus Trading Corp</a>')
    )

    assert owner == inara_client.InaraFactionLink(
        name="Olympus Trading Corp", href="/elite/minorfaction/76647/"
    )


def test_parse_station_owner_distinguishes_unowned_from_malformed():
    assert inara_client.parse_station_owner(_station_page("-")) is None
    with pytest.raises(inara_client.InaraDataError):
        inara_client.parse_station_owner(BeautifulSoup("<div></div>", "html.parser"))


def test_parse_system_factions_reads_active_not_pending_states():
    factions = inara_client.parse_system_factions(
        BeautifulSoup(SYSTEM_FACTIONS_HTML, "html.parser")
    )

    assert factions == {
        "/elite/minorfaction/76647/": ("Infrastructure failure",),
        "/elite/minorfaction/77190/": (),
    }


def test_parse_system_factions_rejects_page_without_table():
    with pytest.raises(inara_client.InaraDataError):
        inara_client.parse_system_factions(BeautifulSoup("<h2>Bodies</h2>", "html.parser"))


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
