import asyncio

import pytest

# Ensure the repository root is on the import path for the tests.
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from gold_detector.config import Settings
from gold_detector.messaging import DiscordMessenger


class _DummyClient:
    def __init__(self, loop: asyncio.AbstractEventLoop):
        self.loop = loop


def _settings() -> Settings:
    return Settings(
        token="token",
        default_alert_channel="market-watch",
        default_role_name="Market Alert",
        alert_channel_override="",
        role_name_override="",
        bot_verbose=False,
        debug_mode=False,
        debug_server_id=None,
        debug_mode_dms=False,
        debug_user_id=None,
        cooldown_hours=48,
        cooldown_seconds=48 * 3600,
        queue_max_size=10,
        help_url="https://example.com",
        monitor_interval_seconds=1.0,
        http_cooldown_seconds=1.0,
        log_level="INFO",
    )


def test_loop_done_waits_for_queue_completion():
    async def _run():
        loop = asyncio.get_running_loop()
        messenger = DiscordMessenger(
            _DummyClient(loop),
            _settings(),
            object(),
            object(),
            object(),
            object(),
            object(),
        )

        drain_called = asyncio.Event()

        def _mark_drain():
            drain_called.set()

        messenger._drain_and_emit_pings = _mark_drain  # type: ignore[assignment]

        messenger.queue.put_nowait((0, "hello"))
        messenger.loop_done_from_thread()

        await asyncio.sleep(0.05)
        assert not drain_called.is_set()

        messenger.queue.task_done()
        await asyncio.wait_for(drain_called.wait(), timeout=1)

    asyncio.run(_run())
