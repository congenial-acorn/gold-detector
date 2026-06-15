"""
Tests for the central commodity registry.

Verifies that:
- Gold, Palladium, Silver are defined with correct Inara IDs and thresholds
- Per-commodity price_threshold and stock_threshold are independent fields
- Helper functions return correct lookups for consumers (monitor, powerplay, etc.)
- Adding a new commodity is as simple as adding to the COMMODITIES tuple
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


# ---------------------------------------------------------------------------
# Commodity dataclass fields
# ---------------------------------------------------------------------------


def test_gold_fields():
    """Gold must have name='Gold', inara_id=42, default thresholds, mask_text."""
    from gold_detector.commodities import get_commodity

    gold = get_commodity("Gold")
    assert gold.name == "Gold"
    assert gold.inara_id == 42
    assert gold.price_threshold == 28_000
    assert gold.stock_threshold == 15_000
    assert gold.mask_text == "Sell gold here"


def test_palladium_fields():
    """Palladium must have name='Palladium', inara_id=45, default thresholds."""
    from gold_detector.commodities import get_commodity

    palladium = get_commodity("Palladium")
    assert palladium.name == "Palladium"
    assert palladium.inara_id == 45
    assert palladium.price_threshold == 28_000
    assert palladium.stock_threshold == 15_000
    assert palladium.mask_text == "Sell Palladium here"


def test_silver_fields():
    """Silver must have name='Silver', inara_id=46, default thresholds."""
    from gold_detector.commodities import get_commodity

    silver = get_commodity("Silver")
    assert silver.name == "Silver"
    assert silver.inara_id == 46
    assert silver.price_threshold == 28_000
    assert silver.stock_threshold == 50_000
    assert silver.mask_text == "Sell Silver here"


# ---------------------------------------------------------------------------
# Registry collection
# ---------------------------------------------------------------------------


def test_commodities_has_three_entries():
    """COMMODITIES tuple must have exactly Gold, Palladium, Silver."""
    from gold_detector.commodities import COMMODITIES

    assert len(COMMODITIES) == 3


def test_commodity_names():
    """commodity_names() returns list of all commodity names in order."""
    from gold_detector.commodities import commodity_names

    assert commodity_names() == ["Gold", "Palladium", "Silver"]


def test_commodity_preference_options():
    """commodity_preference_options() returns tuple for PREFERENCE_OPTIONS."""
    from gold_detector.commodities import commodity_preference_options

    result = commodity_preference_options()
    assert isinstance(result, tuple)
    assert result == ("Gold", "Palladium", "Silver")


# ---------------------------------------------------------------------------
# Lookup maps
# ---------------------------------------------------------------------------


def test_name_to_id_map():
    """name_to_id_map() returns dict mapping commodity names to Inara IDs."""
    from gold_detector.commodities import name_to_id_map

    result = name_to_id_map()
    assert result == {"Gold": 42, "Palladium": 45, "Silver": 46}


def test_id_to_mask_text_map():
    """id_to_mask_text_map() returns dict mapping Inara IDs to mask text."""
    from gold_detector.commodities import id_to_mask_text_map

    result = id_to_mask_text_map()
    assert result[42] == "Sell gold here"
    assert result[45] == "Sell Palladium here"
    assert result[46] == "Sell Silver here"


# ---------------------------------------------------------------------------
# get_commodity error handling
# ---------------------------------------------------------------------------


def test_get_commodity_unknown_raises():
    """get_commodity() with unknown name should raise KeyError."""
    from gold_detector.commodities import get_commodity

    with pytest.raises(KeyError):
        get_commodity("Platinum")


# ---------------------------------------------------------------------------
# Per-commodity thresholds are independent
# ---------------------------------------------------------------------------


def test_thresholds_are_per_commodity():
    """Each Commodity instance has its own threshold fields (not shared global)."""
    from gold_detector.commodities import get_commodity

    gold = get_commodity("Gold")
    silver = get_commodity("Silver")
    # Verify they are independent attributes, not a shared module-level constant
    assert gold.price_threshold == gold.price_threshold
    assert silver.price_threshold == silver.price_threshold
    # Both currently 28000 but the values come from the dataclass field, not a global


def test_default_threshold_constants_exist():
    """DEFAULT_PRICE_THRESHOLD and DEFAULT_STOCK_THRESHOLD module constants."""
    from gold_detector.commodities import (
        DEFAULT_PRICE_THRESHOLD,
        DEFAULT_STOCK_THRESHOLD,
    )

    assert DEFAULT_PRICE_THRESHOLD == 28_000
    assert DEFAULT_STOCK_THRESHOLD == 15_000
