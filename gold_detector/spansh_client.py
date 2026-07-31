from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from gold_detector.http_client import http_get

SPANSH_SYSTEM_URL = "https://spansh.co.uk/api/system"


class SpanshDataError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class SpanshPowerplay:
    power: str
    status: str
    progress: str


def parse_powerplay(payload: object) -> SpanshPowerplay | None:
    if not isinstance(payload, Mapping):
        raise SpanshDataError("Spansh response must be an object")
    record = payload.get("record")
    if not isinstance(record, Mapping):
        raise SpanshDataError("Spansh response is missing record")

    power = record.get("controlling_power")
    status = record.get("power_state")
    if status == "Unoccupied":
        if power is None:
            return None
        raise SpanshDataError("Spansh Unoccupied record has a controlling power")
    if not isinstance(power, str) or not isinstance(status, str):
        raise SpanshDataError("Spansh record has invalid PowerPlay control fields")

    progress = ""
    raw_progress = record.get("power_state_control_progress")
    if isinstance(raw_progress, (int, float)) and not isinstance(raw_progress, bool):
        progress = f"{float(raw_progress):.1%}"

    return SpanshPowerplay(power=power, status=status, progress=progress)


def fetch_powerplay(id64: int) -> SpanshPowerplay | None:
    response = http_get(f"{SPANSH_SYSTEM_URL}/{id64}")
    payload: object = response.json()
    return parse_powerplay(payload)
