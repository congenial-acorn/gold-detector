"""
Tests for alert_helpers module — commodity IDs and URL masking.

Verifies that Silver (Inara commodity ID 46) is supported alongside
Gold (42) and Palladium (45).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def test_silver_inara_id():
    """Silver commodity should have Inara ID 46."""
    from gold_detector.commodities import get_commodity

    assert get_commodity("Silver").inara_id == 46


def test_mask_commodity_links_gold():
    """Regression: mask_commodity_links still masks Gold URLs correctly."""
    from gold_detector.alert_helpers import mask_commodity_links

    url = (
        "https://inara.cz/elite/commodities/?formbrief=1&pi1=2"
        "&pa1%5B%5D=42&ps1=Sol"
    )
    result = mask_commodity_links([url])
    assert "[Sell gold here]" in result
    assert url in result


def test_mask_commodity_links_palladium():
    """Regression: mask_commodity_links still masks Palladium URLs correctly."""
    from gold_detector.alert_helpers import mask_commodity_links

    url = (
        "https://inara.cz/elite/commodities/?formbrief=1&pi1=2"
        "&pa1%5B%5D=45&ps1=Sol"
    )
    result = mask_commodity_links([url])
    assert "[Sell Palladium here]" in result
    assert url in result


def test_mask_commodity_links_silver():
    """mask_commodity_links should mask Silver URLs with 'Sell Silver here'."""
    from gold_detector.alert_helpers import mask_commodity_links

    url = (
        "https://inara.cz/elite/commodities/?formbrief=1&pi1=2"
        "&pa1%5B%5D=46&ps1=Sol"
    )
    result = mask_commodity_links([url])
    assert "[Sell Silver here]" in result
    assert url in result


def test_mask_commodity_links_mixed():
    """mask_commodity_links should handle all three commodities in one call."""
    from gold_detector.alert_helpers import mask_commodity_links

    urls = [
        "https://inara.cz/elite/commodities/?pa1%5B%5D=42",
        "https://inara.cz/elite/commodities/?pa1%5B%5D=45",
        "https://inara.cz/elite/commodities/?pa1%5B%5D=46",
    ]
    result = mask_commodity_links(urls)
    assert "[Sell gold here]" in result
    assert "[Sell Palladium here]" in result
    assert "[Sell Silver here]" in result
