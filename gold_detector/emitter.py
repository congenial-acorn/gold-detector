import logging
from typing import Callable, Optional

logger = logging.getLogger("gold")

# Registered emitters are provided by the bot at runtime.
_emit: Optional[Callable[[str], None]] = None
_emit_loop_done: Optional[Callable[[], None]] = None


def set_emitter(func: Callable[[str], None]) -> None:
    """Register a thread-safe emitter for Discord messages."""
    global _emit
    _emit = func


def set_loop_done_emitter(func: Callable[[], None]) -> None:
    """Register a callback invoked once per monitor loop if any alerts were sent."""
    global _emit_loop_done
    _emit_loop_done = func


def send_to_discord(message: str) -> None:
    """Send a message via the registered emitter, logging a preview for traceability."""
    if _emit is not None:
        _emit(message)
        first_line = message.split("\n")[0]
        logger.info("Alert sent to Discord: %s", first_line[:150])
    else:
        first_line = message.split("\n")[0]
        logger.warning(
            "Discord emitter not wired, message not sent: %s", first_line[:150]
        )


def emit_loop_done() -> None:
    """Invoke the loop-done callback if one has been registered."""
    if _emit_loop_done:
        _emit_loop_done()
