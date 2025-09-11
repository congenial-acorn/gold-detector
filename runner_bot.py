import os
import sys
import asyncio
import time
from typing import Optional

import discord
from discord.ext import tasks
from dotenv import load_dotenv

# ---------- Config ----------
load_dotenv()
TOKEN = os.getenv("DISCORD_BOT_TOKEN")
CHANNEL_ID = int(os.getenv("DISCORD_CHANNEL_ID", "0"))
SCRIPT_PATH = os.getenv("SCRIPT_PATH", "gold.py")

if not TOKEN or not CHANNEL_ID or not SCRIPT_PATH:
    raise SystemExit("Missing DISCORD_BOT_TOKEN, DISCORD_CHANNEL_ID, or SCRIPT_PATH in .env")

# Discord client (no special intents needed to just send messages)
intents = discord.Intents.none()
client = discord.Client(intents=intents)

# Message size budgeting
DISCORD_HARD_LIMIT = 2000
FENCE_OVERHEAD = len("```\n") + len("\n```")
MAX_CHUNK = DISCORD_HARD_LIMIT - FENCE_OVERHEAD  # keep text under 2000 with fences

# Backoff for process restarts
MIN_BACKOFF = 5
MAX_BACKOFF = 60


def wrap_code(s: str) -> str:
    return f"```\n{s}\n```"


def split_chunks(s: str, max_len: int = MAX_CHUNK):
    """Yield <=max_len chunks, splitting on newlines when possible."""
    if not s:
        return
    while s:
        if len(s) <= max_len:
            yield s
            break
        # try to split at the last newline within max_len
        cut = s.rfind("\n", 0, max_len)
        if cut <= 0:
            # no newline found; hard split
            yield s[:max_len]
            s = s[max_len:]
        else:
            yield s[:cut]
            s = s[cut + 1:]


async def send_buffered(channel: discord.TextChannel, prefix: str, buf: str):
    """Send a buffered block (stdout/stderr) in code fences, chunking if needed."""
    if not buf:
        return
    # Optional label at top of each block
    header = f"[{prefix}] " if prefix else ""
    for chunk in split_chunks(buf):
        await channel.send(wrap_code(header + chunk))


async def stream_reader(stream: asyncio.StreamReader, queue: asyncio.Queue, label: str):
    """Read lines from a stream and push them to a queue."""
    while True:
        line = await stream.readline()
        if not line:
            break
        # Decode and normalize line endings
        text = line.decode(errors="replace").rstrip("\r\n")
        await queue.put((label, text))


async def sender_worker(channel: discord.TextChannel, queue: asyncio.Queue):
    """
    Aggregate lines and send them as batched code blocks to reduce message spam.
    Flush every second or when buffer gets large.
    """
    FLUSH_INTERVAL = 1.0
    MAX_BUFFER = MAX_CHUNK  # keep within a single message when possible
    buffers = {"stdout": "", "stderr": ""}
    last_flush = time.monotonic()

    while True:
        try:
            label, line = await asyncio.wait_for(queue.get(), timeout=FLUSH_INTERVAL)
            buf = buffers[label]
            add = (line + "\n")
            if len(buf) + len(add) > MAX_BUFFER:
                await send_buffered(channel, label, buf.rstrip("\n"))
                buffers[label] = add
            else:
                buffers[label] = buf + add
        except asyncio.TimeoutError:
            # periodic flush
            now = time.monotonic()
            if now - last_flush >= FLUSH_INTERVAL:
                for label, buf in list(buffers.items()):
                    if buf:
                        await send_buffered(channel, label, buf.rstrip("\n"))
                        buffers[label] = ""
                last_flush = now


async def run_and_stream(channel: discord.TextChannel):
    """
    Launch gold.py (unbuffered), stream its stdout/stderr to Discord, and
    auto-restart it if it exits (with exponential backoff).
    """
    backoff = MIN_BACKOFF
    while True:
        await channel.send("▶️ Starting script…")
        try:
            # Use unbuffered Python so prints show up immediately
            proc = await asyncio.create_subprocess_exec(
                sys.executable, "-u", SCRIPT_PATH,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env={**os.environ, "PYTHONUNBUFFERED": "1"},
            )
        except Exception as e:
            await channel.send(f"❌ Failed to start process: `{e}`. Retrying in {backoff}s…")
            await asyncio.sleep(backoff)
            backoff = min(MAX_BACKOFF, backoff * 2)
            continue

        queue: asyncio.Queue = asyncio.Queue()
        # Start readers and sender
        tasks = [
            asyncio.create_task(stream_reader(proc.stdout, queue, "stdout")),
            asyncio.create_task(stream_reader(proc.stderr, queue, "stderr")),
            asyncio.create_task(sender_worker(channel, queue)),
        ]

        # Wait for process to end
        rc: Optional[int] = None
        try:
            rc = await proc.wait()
        finally:
            for t in tasks:
                t.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

        await channel.send(f"⏹️ Script exited with code `{rc}`. Restarting in {backoff}s…")
        await asyncio.sleep(backoff)
        backoff = min(MAX_BACKOFF, max(MIN_BACKOFF, backoff * 2))


@client.event
async def on_ready():
    channel = client.get_channel(CHANNEL_ID)
    if not isinstance(channel, (discord.TextChannel, discord.Thread)):
        # Try fetching if get_channel returned None
        try:
            fetched = await client.fetch_channel(CHANNEL_ID)
            channel = fetched
        except Exception:
            raise RuntimeError("Could not find the target channel. Check DISCORD_CHANNEL_ID.")
    # Kick off the runner
    client.loop.create_task(run_and_stream(channel))
    print(f"Logged in as {client.user} → streaming {SCRIPT_PATH} to #{getattr(channel, 'name', channel.id)}")


def main():
    client.run(TOKEN)


if __name__ == "__main__":
    main()
