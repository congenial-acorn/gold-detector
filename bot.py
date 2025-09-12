import os
import time
import asyncio
import threading
from typing import Optional, Dict
from pathlib import Path

import discord
from dotenv import load_dotenv, find_dotenv

import gold  # gold.py must be importable (same folder or on PYTHONPATH)

# Load .env (CWD first, then next to this file)
_ = load_dotenv(find_dotenv())
if not os.getenv("DISCORD_TOKEN"):
    load_dotenv(Path(__file__).with_name(".env"))

TOKEN = os.getenv("DISCORD_TOKEN")
ALERT_CHANNEL_NAME = os.getenv("ALERT_CHANNEL_NAME", "").strip()
ROLE_NAME = os.getenv("ROLE_NAME", "").strip()
BOT_VERBOSE = os.getenv("BOT_VERBOSE", "1") == "1"

def log(msg: str):
    if BOT_VERBOSE:
        print(msg, flush=True)
        
def _to_float(env_key: str, default: float) -> float:
    try:
        return float(os.getenv(env_key, str(default)))
    except ValueError:
        return default

BURST_MINUTES = _to_float("BURST_MINUTES", 8.0)
COOLDOWN_HOURS = _to_float("COOLDOWN_HOURS", 48.0)

BURST_SECONDS = int(BURST_MINUTES * 60)
COOLDOWN_SECONDS = int(COOLDOWN_HOURS * 3600)

if not TOKEN:
    raise SystemExit("Missing DISCORD_TOKEN in .env")
if not ALERT_CHANNEL_NAME:
    raise SystemExit("ALERT_CHANNEL_NAME is required in .env")

intents = discord.Intents.default()
intents.guilds = True
client = discord.Client(intents=intents)

queue: asyncio.Queue[str] = asyncio.Queue()

# Per-server and per-message cooldown state
# Structure: {guild_id -> {message_id -> timestamp of last send}}
_server_message_cooldowns: Dict[int, Dict[int, float]] = {}

# ---------- Channel / Role helpers ----------

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

# ---------- Per-server and per-message cooldown logic ----------

async def _should_send_and_update(guild_id: int, message_id: int, now: float):
    """
    Check and update cooldown for a specific message in a specific server.
    Returns (allow: bool, previous_timestamp: float|None, remaining_seconds: float|None).
    """
    if guild_id not in _server_message_cooldowns:
        _server_message_cooldowns[guild_id] = {}

    prev_timestamp = _server_message_cooldowns[guild_id].get(message_id)
    
    if prev_timestamp is None or now - prev_timestamp >= COOLDOWN_SECONDS:
        # If the message doesn't have a cooldown or the cooldown has expired, allow sending
        _server_message_cooldowns[guild_id][message_id] = now  # Update the timestamp for this message
        return True, prev_timestamp, None
    else:
        # Cooldown is still active, calculate remaining time
        remaining_time = COOLDOWN_SECONDS - (now - prev_timestamp)
        return False, prev_timestamp, remaining_time

# ---------- Sending ----------

async def _send_to_guild(guild: discord.Guild, content: str, message_id: int):
    now = time.time()
    guild_id = guild.id

    # Check and apply cooldown for this specific message and server
    allow, prev_timestamp, remaining = await _should_send_and_update(guild_id, message_id, now)
    if not allow:
        hrs = remaining / 3600 if remaining else 0.0
        log(f"[{guild.name}] Cooldown active for message {message_id} in this server; skipping. ~{hrs:.2f}h remaining.")
        return

    ch = await _named_sendable_channel(guild, ALERT_CHANNEL_NAME)
    if not ch:
        log(f"[{guild.name}] No send permission to a channel named '#{ALERT_CHANNEL_NAME}'. Skipping.")
        return

    role = _find_role_by_name(guild)
    prefix = f"{role.mention} " if role else ""
    allowed_mentions = discord.AllowedMentions(roles=True, users=False, everyone=False)

    # Ensure no link embeds are shown by passing the 'allowed_mentions' argument
    try:
        await ch.send(f"{prefix}{content}", allowed_mentions=allowed_mentions, embed=None)  # `embed=None` prevents embeds
        if prev_timestamp is None:
            log(f"[{guild.name}] Sent to #{ch.name}. (First message, burst window starts now)")
        else:
            log(f"[{guild.name}] Sent to #{ch.name}. (Cooldown applied for message {message_id})")
    except Exception as e:
        log(f"[{guild.name}] ERROR sending message: {e}")

# ---------- Dispatcher & Lifecycle ----------

async def _dispatcher_loop():
    await client.wait_until_ready()
    while True:
        msg = await queue.get()
        message_id = hash(msg)  # Use the hash of the message content as its unique ID
        try:
            tasks = [asyncio.create_task(_send_to_guild(g, msg, message_id)) for g in client.guilds]
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
    log(f"Cooldown after each message: {COOLDOWN_HOURS:g} hours")

    # Wire gold.py -> async queue
    if hasattr(gold, "set_emitter"):
        gold.set_emitter(lambda m: queue.put_nowait(m))
        log("Emitter registered via gold.set_emitter(...)")
    else:
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

    # Start dispatcher
    asyncio.create_task(_dispatcher_loop())

if __name__ == "__main__":
    client.run(TOKEN)
