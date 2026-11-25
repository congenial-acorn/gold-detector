from pathlib import Path

from gold_detector.services import GuildPreferencesService


def _service(path: Path) -> GuildPreferencesService:
    return GuildPreferencesService(
        path,
        default_channel="market-watch",
        default_role="Market Alert",
        channel_override="",
        role_override="",
    )


def test_stock_thresholds_persist_reset_and_clear(tmp_path):
    path = tmp_path / "guild_prefs.json"
    prefs = _service(path)

    assert prefs.set_stock_threshold("user", 1, "Gold", 8_000) == 8_000
    assert prefs.set_stock_threshold("guild", 2, "Silver", 30_000) == 30_000
    prefs.set_preferences("guild", 2, "commodity", ["Silver"])

    reloaded = _service(path)
    assert reloaded.get_preferences("user", 1) == {"stock_threshold": {"Gold": 8_000}}
    assert reloaded.get_preferences("guild", 2) == {
        "commodity": ["Silver"],
        "stock_threshold": {"Silver": 30_000},
    }

    assert reloaded.set_stock_threshold("user", 1, "Gold", None) == 15_000
    assert reloaded.get_preferences("user", 1) == {}
    reloaded.clear_category("guild", 2, "stock_threshold")
    assert _service(path).get_preferences("guild", 2) == {"commodity": ["Silver"]}


def test_invalid_stored_stock_thresholds_are_dropped(tmp_path):
    path = tmp_path / "guild_prefs.json"
    path.write_text(
        '{"guilds": {}, "users": {"1": {"stock_threshold": '
        '{"gold": 5000, "Silver": -1, "Palladium": "x", "Tritium": 10}}}}'
    )

    assert _service(path).get_preferences("user", 1) == {
        "stock_threshold": {"Gold": 5_000}
    }
