import os
import sys
import time
import asyncio
import threading
from typing import Optional, Dict
from pathlib import Path

import discord
from dotenv import load_dotenv, find_dotenv

import gold  # gold.py must be importable (same folder or on PYTHONPATH)

# Load .env (search CWD, then next to this file)
_ = load_dotenv(find_dotenv())
if not os.getenv("DISCORD_TOKEN"):
    load_dotenv(Path(__file__).with_name(".env"))

TOKEN = os.getenv("DISCORD_TOKEN")
ALERT_CHANNEL_NAME = os.getenv("ALERT_CHANNEL_NAME", "").strip()
ROLE_NAME = os.getenv("ROLE_NAME", "").strip()
BOT_VERBOSE = os.getenv("BOT_VERBOSE", "1") == "1"
try:
    COOLDOWN_HOURS = float(os.getenv("COOLDOWN_HOURS", "48"))
except ValueError:
    COOLDOWN_HOURS = 48.0
COOLDOWN_SECONDS = int(COOLDOWN_HOURS * 3600)

if not TOKEN:
    raise SystemExit("Missing DISCORD_TOKEN in .env")
if not ALERT_CHANNEL_NAME:
    raise SystemExit("ALERT_CHANNEL_NAME is required in .env")

intents = discord.Intents.default()
intents.guilds = True
client = discord.Client(intents=intents)

queue: asyncio.Queue[str] = asyncio.Queue()

# Per-server cooldown store
_cooldown_lock = asyncio.Lock()
_last_sent: Dict[int, float] = {}  # guild_id -> epoch seconds of last successful send

def log(*a):
    if BOT_VERBOSE:
        print(*a, flush=True)

async def _named_sendable_channel(guild: discord.Guild, name: str) -> Optional[discord.TextChannel]:
    """Return the first sendable text channel matching the given name (case-insensitive)."""
    name_lower = name.lower()
    for ch in sorted(guild.text_channels, key=lambda c: (c.position, c.id)):
        if ch.name.lower() == name_lower:
            perms = ch.permissions_for(guild.me)
            if perms.view_channel and perms.send_messages:
                return ch
    return None

def _find_role_by_name(guild: discord.Guild) -> Optional[discord.Role]:
    """Return a role by case-insensitive name, or None if not found.
       NOTE: Without Manage Roles or Mention Everyone, the role must be allow-mentionable
       for notifications to actually ping members."""
    if not ROLE_NAME:
        return None
    target = ROLE_NAME.lower()
    for r in guild.roles:
        if r.name.lower() == target:
            return r
    return None

async def _should_send_and_mark(guild_id: int) -> tuple[bool, Optional[float]]:
    """Atomically check cooldown for guild; if allowed, mark 'now' and return (True, previous_last).
       If not allowed, return (False, last)."""
    now = time.time()
    async with _cooldown_lock:
        last = _last_sent.get(guild_id)
        if last is None or (now - last) >= COOLDOWN_SECONDS:
            _last_sent[guild_id] = now
            return True, last
        return False, last

async def _rollback_last_sent(guild_id: int, prev_last: Optional[float]) -> None:
    """If send fails, roll back the last_sent timestamp to the previous value."""
    async with _cooldown_lock:
        if prev_last is None:
            _last_sent.pop(guild_id, None)
        else:
            _last_sent[guild_id] = prev_last

async def _send_to_guild(guild: discord.Guild, content: str):
    # Cooldown gate
    allowed, prev_last = await _should_send_and_mark(guild.id)
    if not allowed:
        # compute a friendly remaining time for logs
        now = time.time()
        remaining = max(0, COOLDOWN_SECONDS - (now - (prev_last or 0)))
        hrs = remaining / 3600
        log(f"[{guild.name}] Cooldown active; skipping. ~{hrs:.2f}h remaining.")
        return

    ch = await _named_sendable_channel(guild, ALERT_CHANNEL_NAME)
    if not ch:
        log(f"[{guild.name}] No send permission to a channel named '#{ALERT_CHANNEL_NAME}'. Skipping.")
        # roll back cooldown mark since we did not send
        await _rollback_last_sent(guild.id, prev_last)
        return

    role = _find_role_by_name(guild)
    prefix = f"{role.mention} " if role else ""
    allowed_mentions = discord.AllowedMentions(roles=True, users=False, everyone=False)

    try:
        await ch.send(f"{prefix}{content}", allowed_mentions=allowed_mentions)
        log(f"[{guild.name}] Sent to #{ch.name}. (Cooldown: {COOLDOWN_HOURS:g}h)")
    except Exception as e:
        log(f"[{guild.name}] ERROR sending message: {e}")
        # roll back cooldown mark on failure
        await _rollback_last_sent(guild.id, prev_last)

async def _dispatcher_loop():
    await client.wait_until_ready()
    while True:
        msg = await queue.get()
        try:
            tasks = [asyncio.create_task(_send_to_guild(g, msg)) for g in client.guilds]
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
        finally:
            queue.task_done()

@client.event
async def on_ready():
    log(f"✅ Logged in as {client.user} (id={client.user.id})")
    log(f"Posting only to channels named: #{ALERT_CHANNEL_NAME}")
    if ROLE_NAME:
        log(f"Optional role mention: @{ROLE_NAME}")
    log(f"Per-server cooldown: {COOLDOWN_HOURS:g} hours")

    # Wire gold.py -> async queue
    if hasattr(gold, "set_emitter"):
        gold.set_emitter(lambda m: queue.put_nowait(m))
        log("Emitter registered via gold.set_emitter(...)")
    else:
        # Fallback: monkey-patch if gold already defines send_to_discord (same-process only)
        if hasattr(gold, "send_to_discord") and callable(getattr(gold, "send_to_discord")):
            setattr(gold, "send_to_discord", lambda m: queue.put_nowait(m))
            log("Emitter installed by monkey-patching gold.send_to_discord(...)")
        else:
            log("WARNING: gold.py lacks set_emitter()/send_to_discord(); add the shim shown below.")

    # Start gold.py forever inside this process (so it's always running with the bot)
    def run_gold_forever():
        try:
            if hasattr(gold, "main") and callable(getattr(gold, "main")):
                gold.main()  # your long-running loop lives here
            else:
                log("ERROR: gold.py has no main(); move your __main__ code into a main() function.")
        except Exception as e:
            log(f"[gold.py] exited with error: {e}")

    threading.Thread(target=run_gold_forever, name="gold-runner", daemon=True).start()
    log("Started gold.py in background thread.")

    # Start dispatcher that relays messages to all guilds (subject to cooldown)
    asyncio.create_task(_dispatcher_loop())

if __name__ == "__main__":
    client.run(TOKEN)
