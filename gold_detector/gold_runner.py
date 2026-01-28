from __future__ import annotations

import logging
import threading
import time
from typing import Callable, Optional

import gold


class GoldRunner:
    def __init__(
        self,
        emit: Optional[Callable[[str], None]],
        loop_done: Optional[Callable[[], None]],
        logger: Optional[logging.Logger] = None,
    ):
        self.emit = emit
        self.loop_done = loop_done
        self.logger = logger or logging.getLogger("bot.gold_runner")

    def start(self) -> threading.Thread:
        thread = threading.Thread(target=self._run, name="gold-runner", daemon=True)
        thread.start()
        return thread

    def _run(self) -> None:
        max_backoff = 3600
        base = 5
        backoff = base
        consecutive_failures = 0

        while True:
            try:
                if hasattr(gold, "main") and callable(getattr(gold, "main")):
                    self.logger.info("Starting gold.py main loop")
                    gold.main()
                    raise RuntimeError(
                        "gold.py main() returned unexpectedly (no exception raised)"
                    )

                self.logger.error(
                    "ERROR: gold.py has no main(); move your __main__ code into a main() function."
                )
                break

            except KeyboardInterrupt:
                self.logger.info(
                    "Received KeyboardInterrupt, shutting down gold.py thread"
                )
                raise
            except BaseException as exc:  # noqa: BLE001
                consecutive_failures += 1
                message = str(exc)

                self.logger.error(
                    "gold.py crashed (attempt #%s): %s: %s",
                    consecutive_failures,
                    type(exc).__name__,
                    exc,
                    exc_info=True,
                )

                if (
                    "IP address blocked" in message
                    or "Access Temporarily Restricted" in message
                ):
                    self.logger.error(
                        "CRITICAL: IP blocked by inara.cz. "
                        "Contact inara@inara.cz with your IP address to resolve. "
                        "Will retry in %ss but likely to fail until unblocked.",
                        backoff,
                    )
                elif "429" in message:
                    self.logger.warning(
                        "HTTP 429 rate limit; restarting in %ss", backoff
                    )
                elif "Connection" in message or "Timeout" in message:
                    self.logger.error(
                        "Network error: %s; restarting in %ss", message, backoff
                    )
                else:
                    self.logger.error("Unexpected error; restarting in %ss", backoff)

                if consecutive_failures >= 5:
                    self.logger.warning(
                        "gold.py has crashed %s times consecutively. "
                        "Check for persistent issues.",
                        consecutive_failures,
                    )

                time.sleep(backoff)
                backoff = min(backoff * 2, max_backoff)
                self.logger.info(
                    "Attempting to restart gold.py (backoff now %ss)", backoff
                )
