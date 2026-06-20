"""Central commodity registry for the Gold Detector bot.

All commodity properties live here.  Adding a new commodity requires only
adding a :class:`Commodity` entry to the :data:`COMMODITIES` tuple below —
every other module (monitor, powerplay, alert_helpers, services, gold)
auto-derives from the registry.

Example - adding a new commodity::

    COMMODITIES = (
        ...,
        Commodity(
            name="Platinum",
            inara_id=50,
            price_threshold=30_000,
            stock_threshold=10_000,
            mask_text="Sell Platinum here",
        ),
    )
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Tuple

# Default thresholds — used when a Commodity omits explicit values.
DEFAULT_PRICE_THRESHOLD: int = 28_000
DEFAULT_STOCK_THRESHOLD: int = 15_000


@dataclass(frozen=True)
class Commodity:
    """A single tradeable metal monitored by the bot.

    Attributes:
        name: Human-readable commodity name (e.g. ``"Gold"``).
            Used as the dictionary key in the market database and as the
            display string in Discord messages.
        inara_id: Inara.cz internal commodity ID used in URL construction
            (the ``pa1%5B%5D`` query parameter).
        price_threshold: Minimum buy price (CR/ton) for a station to be
            considered an alert-worthy opportunity.  Defaults to
            :data:`DEFAULT_PRICE_THRESHOLD`.
        stock_threshold: Minimum stock (tons) for a station to be
            considered an alert-worthy opportunity.  Defaults to
            :data:`DEFAULT_STOCK_THRESHOLD`.
        mask_text: Display text used when masking commodity URLs in
            Discord messages (e.g. ``"Sell gold here"``).
    """

    name: str
    inara_id: int
    price_threshold: int = DEFAULT_PRICE_THRESHOLD
    stock_threshold: int = DEFAULT_STOCK_THRESHOLD
    mask_text: str = "Sell here"


# ---------------------------------------------------------------------------
# Registry — edit this tuple to add / remove / reorder commodities.
# ---------------------------------------------------------------------------

COMMODITIES: Tuple[Commodity, ...] = (
    Commodity(name="Gold", inara_id=42, mask_text="Sell gold here"),
    Commodity(name="Palladium", inara_id=45, mask_text="Sell Palladium here"),
    Commodity(
        name="Silver", inara_id=46, stock_threshold=50000, mask_text="Sell Silver here"
    ),
)

# Pre-built lookup tables (module-level so they are built once at import).
_BY_NAME: Dict[str, Commodity] = {c.name: c for c in COMMODITIES}
_BY_ID: Dict[int, Commodity] = {c.inara_id: c for c in COMMODITIES}


# ---------------------------------------------------------------------------
# Public helper functions
# ---------------------------------------------------------------------------


def get_commodity(name: str) -> Commodity:
    """Return the :class:`Commodity` for *name*.

    Raises:
        KeyError: if *name* is not in the registry.
    """
    return _BY_NAME[name]


def get_commodity_by_id(inara_id: int) -> Commodity:
    """Return the :class:`Commodity` for *inara_id*.

    Raises:
        KeyError: if *inara_id* is not in the registry.
    """
    return _BY_ID[inara_id]


def commodity_names() -> List[str]:
    """Return commodity names in registry order (used as the monitor's metals list)."""
    return [c.name for c in COMMODITIES]


def commodity_preference_options() -> Tuple[str, ...]:
    """Return commodity names as a tuple (for ``PREFERENCE_OPTIONS``)."""
    return tuple(c.name for c in COMMODITIES)


def name_to_id_map() -> Dict[str, int]:
    """Return ``{name: inara_id}`` mapping (used by powerplay link builder)."""
    return {c.name: c.inara_id for c in COMMODITIES}


def id_to_mask_text_map() -> Dict[int, str]:
    """Return ``{inara_id: mask_text}`` mapping (used by URL masking)."""
    return {c.inara_id: c.mask_text for c in COMMODITIES}
