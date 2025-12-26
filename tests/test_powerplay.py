import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import gold  # noqa: E402


class FakeResponse:
    def __init__(self, text: str):
        self.text = text


def _pp_html(status: str, percent: str = "51.8%"):
    return f"""
    <html>
      <body>
        <h2>Sol \\ue81d</h2>
        <div>
          <span class="uppercase minor small">Powerplay</span><br/>
          <a href="/elite/power/12/">Jerome Archer</a>
          <small>(Controlling)</small><br/>
          <span class="bigger"><span class="positive">{status}</span></span>
          <span class="negative"><br/>{percent}</span>
        </div>
      </body>
    </html>
    """


def test_powerplay_fortified_builds_links(monkeypatch):
    calls = []

    monkeypatch.setattr(gold, "send_to_discord", lambda msg: calls.append(msg))
    monkeypatch.setattr(
        gold, "http_get", lambda url: FakeResponse(_pp_html("Fortified"))
    )

    systems = [["https://inara.cz/elite/starsystem/345798/", "Gold", "Palladium"]]
    gold.get_powerplay_status(systems)

    assert len(calls) == 2  # Fortified alert + info message
    assert "Fortified" in calls[0]
    assert "Sol" in calls[0]
    assert "pa1%5B%5D=42" in calls[0] and "pa1%5B%5D=45" in calls[0]
    assert "pi11=20" in calls[0]  # distance for Fortified branch


def test_powerplay_stronghold_uses_distance_30(monkeypatch):
    calls = []

    monkeypatch.setattr(gold, "send_to_discord", lambda msg: calls.append(msg))
    monkeypatch.setattr(
        gold, "http_get", lambda url: FakeResponse(_pp_html("Stronghold"))
    )

    systems = [["https://inara.cz/elite/starsystem/1496596/", "Gold"]]
    gold.get_powerplay_status(systems)

    assert len(calls) == 2  # Stronghold alert + info message
    assert "Stronghold" in calls[0]
    assert "pa1%5B%5D=42" in calls[0]
    assert "pa1%5B%5D=45" not in calls[0]
    assert "pi11=30" in calls[0]  # distance for Stronghold branch
