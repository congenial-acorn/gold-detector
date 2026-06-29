import json
import sys
import threading
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from gold_detector.market_database import MarketDatabase


@pytest.fixture
def db_path(tmp_path):
    return tmp_path / "market_database.json"


@pytest.fixture
def db(db_path):
    return MarketDatabase(db_path)


def load_data(path: Path) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def assert_no_cooldowns(value):
    if isinstance(value, dict):
        assert "cooldowns" not in value
        for nested in value.values():
            assert_no_cooldowns(nested)
    elif isinstance(value, list):
        for nested in value:
            assert_no_cooldowns(nested)


def test_init_migrates_legacy_cooldowns_from_metals_and_powerplay(db_path):
    legacy_data = {
        "Sol": {
            "system_address": "10477373803",
            "powerplay": {
                "power": "Zachary Hudson",
                "status": "Fortified",
                "progress": 75,
                "commodity_urls": "links",
                "cooldowns": {"guild": {"1": 123.0}},
            },
            "stations": {
                "Abraham Lincoln": {
                    "station_type": "Coriolis Starport",
                    "url": "https://inara.cz/station/123",
                    "metals": {
                        "Gold": {
                            "stock": 25000,
                            "cooldowns": {"guild": {"1": 123.0}},
                        },
                        "Silver": {
                            "stock": 50000,
                            "sent_to": {"guild": {"2": True}, "user": {}},
                            "cooldowns": {"user": {"3": 456.0}},
                        },
                    },
                }
            },
        }
    }
    with open(db_path, "w", encoding="utf-8") as handle:
        json.dump(legacy_data, handle, indent=2, sort_keys=True)

    migrated = MarketDatabase(db_path)
    data = migrated.read_all_entries()

    assert_no_cooldowns(data)
    assert data["Sol"]["stations"]["Abraham Lincoln"]["metals"]["Gold"] == {
        "stock": 25000,
        "sent_to": {"guild": {}, "user": {}},
    }
    assert data["Sol"]["stations"]["Abraham Lincoln"]["metals"]["Silver"] == {
        "stock": 50000,
        "sent_to": {"guild": {"2": True}, "user": {}},
    }
    assert "cooldowns" not in load_data(db_path)["Sol"]["powerplay"]


def test_write_market_entry_preserves_existing_sent_to_and_initializes_new(db, db_path):
    db.write_market_entry(
        system_name="Sol",
        system_address="10477373803",
        station_name="Abraham Lincoln",
        station_type="Coriolis Starport",
        url="https://inara.cz/station/123",
        metal="Gold",
        stock=25000,
    )
    db.mark_market_alerts_sent_batch(
        [
            ("Sol", "Abraham Lincoln", "Gold", "guild", "123"),
            ("Sol", "Abraham Lincoln", "Gold", "user", "456"),
        ]
    )

    db.write_market_entry(
        system_name="Sol",
        system_address="10477373803",
        station_name="Abraham Lincoln",
        station_type="Coriolis Starport",
        url="https://inara.cz/station/123",
        metal="Gold",
        stock=30000,
    )
    db.write_market_entry(
        system_name="Sol",
        system_address="10477373803",
        station_name="Abraham Lincoln",
        station_type="Coriolis Starport",
        url="https://inara.cz/station/123",
        metal="Silver",
        stock=60000,
    )

    data = load_data(db_path)
    assert data["Sol"]["stations"]["Abraham Lincoln"]["metals"]["Gold"] == {
        "stock": 30000,
        "sent_to": {"guild": {"123": True}, "user": {"456": True}},
    }
    assert data["Sol"]["stations"]["Abraham Lincoln"]["metals"]["Silver"] == {
        "stock": 60000,
        "sent_to": {"guild": {}, "user": {}},
    }


def test_write_powerplay_entry_never_writes_or_preserves_cooldowns(db_path):
    legacy_data = {
        "Sol": {
            "system_address": "10477373803",
            "powerplay": {
                "power": "Old Power",
                "status": "Fortified",
                "progress": 30,
                "commodity_urls": "old",
                "cooldowns": {"guild": {"1": 123.0}},
            },
            "stations": {},
        }
    }
    with open(db_path, "w", encoding="utf-8") as handle:
        json.dump(legacy_data, handle, indent=2, sort_keys=True)

    db = MarketDatabase(db_path)
    db.write_powerplay_entry(
        system_name="Sol",
        system_address="10477373803",
        power="Zachary Hudson",
        status="Stronghold",
        progress=80,
        commodity_urls="links",
    )

    data = load_data(db_path)
    assert data["Sol"]["powerplay"] == {
        "power": "Zachary Hudson",
        "status": "Stronghold",
        "progress": 80,
        "commodity_urls": "links",
    }


def test_mark_market_alerts_sent_batch_and_has_market_alert_been_sent(db, db_path):
    db.write_market_entry(
        system_name="Sol",
        system_address="10477373803",
        station_name="Abraham Lincoln",
        station_type="Coriolis Starport",
        url="https://inara.cz/station/123",
        metal="Gold",
        stock=25000,
    )

    db.mark_market_alerts_sent_batch(
        [
            ("Sol", "Abraham Lincoln", "Gold", "guild", "123"),
            ("Sol", "Abraham Lincoln", "Gold", "guild", "789"),
            ("Sol", "Abraham Lincoln", "Gold", "user", "456"),
        ]
    )

    assert (
        db.has_market_alert_been_sent("Sol", "Abraham Lincoln", "Gold", "guild", "123")
        is True
    )
    assert (
        db.has_market_alert_been_sent("Sol", "Abraham Lincoln", "Gold", "guild", "789")
        is True
    )
    assert (
        db.has_market_alert_been_sent("Sol", "Abraham Lincoln", "Gold", "user", "456")
        is True
    )
    assert (
        db.has_market_alert_been_sent("Sol", "Abraham Lincoln", "Gold", "guild", "456")
        is False
    )
    assert (
        db.has_market_alert_been_sent("Sol", "Abraham Lincoln", "Gold", "user", "123")
        is False
    )
    assert (
        db.has_market_alert_been_sent("Sol", "Abraham Lincoln", "Gold", "guild", "999")
        is False
    )

    reloaded = MarketDatabase(db_path)
    assert (
        reloaded.has_market_alert_been_sent(
            "Sol", "Abraham Lincoln", "Gold", "guild", "123"
        )
        is True
    )


def test_prune_stale_removes_only_absent_opportunities_and_cascades_empty_containers(
    db, db_path
):
    db.write_market_entry(
        system_name="Sol",
        system_address="10477373803",
        station_name="Abraham Lincoln",
        station_type="Coriolis Starport",
        url="https://inara.cz/station/123",
        metal="Gold",
        stock=25000,
    )
    db.write_market_entry(
        system_name="Sol",
        system_address="10477373803",
        station_name="Abraham Lincoln",
        station_type="Coriolis Starport",
        url="https://inara.cz/station/123",
        metal="Silver",
        stock=60000,
    )
    db.write_market_entry(
        system_name="Alpha Centauri",
        system_address="123456789",
        station_name="Hutton Orbital",
        station_type="Outpost",
        url="https://inara.cz/station/789",
        metal="Palladium",
        stock=16000,
    )
    db.mark_market_alerts_sent_batch(
        [
            ("Sol", "Abraham Lincoln", "Gold", "guild", "123"),
            ("Sol", "Abraham Lincoln", "Silver", "user", "456"),
            ("Alpha Centauri", "Hutton Orbital", "Palladium", "guild", "999"),
        ]
    )

    db.prune_stale({("Sol", "Abraham Lincoln", "Silver")})

    data = load_data(db_path)
    metals = data["Sol"]["stations"]["Abraham Lincoln"]["metals"]
    assert "Gold" not in metals
    assert metals["Silver"] == {
        "stock": 60000,
        "sent_to": {"guild": {}, "user": {"456": True}},
    }
    assert "Alpha Centauri" not in data


def test_prune_stale_removes_powerplay_for_absent_systems_but_preserves_stations(
    db, db_path
):
    db.write_market_entry(
        system_name="Sol",
        system_address="10477373803",
        station_name="Abraham Lincoln",
        station_type="Coriolis Starport",
        url="https://inara.cz/station/123",
        metal="Gold",
        stock=25000,
    )
    db.write_powerplay_entry(
        system_name="Sol",
        system_address="10477373803",
        power="Zachary Hudson",
        status="Fortified",
        progress=75,
        commodity_urls="links",
    )

    db.prune_stale(
        {("Sol", "Abraham Lincoln", "Gold")}, current_powerplay_systems=set()
    )

    data = load_data(db_path)
    assert "powerplay" not in data["Sol"]
    assert (
        data["Sol"]["stations"]["Abraham Lincoln"]["metals"]["Gold"]["stock"] == 25000
    )


def test_end_scan_uses_opportunity_and_powerplay_sets(db, db_path):
    db.write_market_entry(
        system_name="Sol",
        system_address="10477373803",
        station_name="Abraham Lincoln",
        station_type="Coriolis Starport",
        url="https://inara.cz/station/123",
        metal="Gold",
        stock=25000,
    )
    db.write_market_entry(
        system_name="Alpha Centauri",
        system_address="123456789",
        station_name="Hutton Orbital",
        station_type="Outpost",
        url="https://inara.cz/station/789",
        metal="Palladium",
        stock=16000,
    )
    db.write_powerplay_entry(
        system_name="Sol",
        system_address="10477373803",
        power="Zachary Hudson",
        status="Fortified",
        progress=75,
        commodity_urls="links",
    )
    db.write_powerplay_entry(
        system_name="Alpha Centauri",
        system_address="123456789",
        power="Aisling Duval",
        status="Stronghold",
        progress=55,
        commodity_urls="links",
    )

    db.begin_scan()
    db.end_scan({("Sol", "Abraham Lincoln", "Gold")}, {"Sol"})

    data = load_data(db_path)
    assert "Sol" in data
    assert "Alpha Centauri" not in data
    assert data["Sol"]["powerplay"]["power"] == "Zachary Hudson"


def test_concurrent_writes_and_batch_marks_do_not_corrupt_file(db, db_path):
    errors = []

    def write_many(system_name, station_name, metal):
        try:
            for index in range(10):
                db.write_market_entry(
                    system_name=system_name,
                    system_address=f"addr-{system_name}",
                    station_name=station_name,
                    station_type="Starport",
                    url=f"https://inara.cz/station/{station_name}",
                    metal=metal,
                    stock=1000 + index,
                )
                db.mark_market_alerts_sent_batch(
                    [(system_name, station_name, metal, "guild", str(index))]
                )
        except Exception as exc:
            errors.append(exc)

    threads = [
        threading.Thread(target=write_many, args=("Sol", "Station1", "Gold")),
        threading.Thread(target=write_many, args=("Sol", "Station2", "Silver")),
        threading.Thread(target=write_many, args=("Achenar", "Station3", "Palladium")),
    ]

    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert errors == []
    data = load_data(db_path)
    assert "Sol" in data
    assert "Achenar" in data
    assert data["Sol"]["stations"]["Station1"]["metals"]["Gold"]["sent_to"]["guild"]


def test_atomic_write_does_not_replace_existing_file_on_save_failure(
    db, db_path, monkeypatch
):
    db.write_market_entry(
        system_name="Sol",
        system_address="10477373803",
        station_name="Abraham Lincoln",
        station_type="Coriolis Starport",
        url="https://inara.cz/station/123",
        metal="Gold",
        stock=25000,
    )
    original = db_path.read_text(encoding="utf-8")
    original_dump = json.dump

    def crash_dump(*args, **kwargs):
        raise RuntimeError("Simulated crash")

    monkeypatch.setattr(json, "dump", crash_dump)
    with pytest.raises(RuntimeError):
        db.write_market_entry(
            system_name="Sol",
            system_address="10477373803",
            station_name="Abraham Lincoln",
            station_type="Coriolis Starport",
            url="https://inara.cz/station/123",
            metal="Gold",
            stock=30000,
        )
    monkeypatch.setattr(json, "dump", original_dump)

    assert db_path.read_text(encoding="utf-8") == original
    assert not db_path.with_suffix(db_path.suffix + ".tmp").exists()
