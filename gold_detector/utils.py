from __future__ import annotations

import time
from hashlib import blake2b


def message_key(text: str) -> int:
    """Stable 64-bit hash for deduplicating messages."""
    digest = blake2b(text.encode("utf-8"), digest_size=8)
    return int.from_bytes(digest.digest(), "big")


def now() -> float:
    return time.time()

