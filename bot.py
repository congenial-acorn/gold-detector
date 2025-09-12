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

def log(*a):
    if BOT_VERBOSE:
        print(*a, flush=True)

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

# ---------- Per-server burst+cooldown state ----------

_state_lock = asyncio.Lock()
# guild_id -> {'burst_start': float|None, 'cooldown_until': float|None}
_state: Dict[int, Dict[str, Optional[float]]] = {}

async def _should_send_and_update(guild_id: int, now: float):
    """
    Decide if we should send for this guild given burst/cooldown rules.
    Returns (allow: bool, prev_snapshot: Optional[dict], remaining_seconds: Optional[float]).
    If allow=True and prev_snapshot is not None, state changed (we started a new burst) and can be rolled back on failure.
    """
    async with _state_lock:
        st = _state.get(guild_id)
        if st is None:
            st = {'burst_start': None, 'cooldown_until': None}
            _state[guild_id] = st

        # If currently in cooldown, skip
        if st['cooldown_until'] is not None and now < st['cooldown_until']:
            return False, None, st['cooldown_until'] - now

        # Not in cooldown
        if st['burst_start'] is None:
            # Start a new burst now
            prev = st.copy()
            st['burst_start'] = now
            st['cooldown_until'] = None
            return True, prev, None

        window_end = st['burst_start'] + BURST_SECONDS
        if now <= window_end:
            # Still inside the burst window — allow send, no state change
            return True, None, None

        # Burst has ended; set cooldown if not already set
        st['cooldown_until'] = window_end + COOLDOWN_SECONDS

        # After setting cooldown, check if we are still before cooldown end
        if now < st['cooldown_until']:
            return False, None, st['cooldown_until'] - now

        # Cooldown already elapsed — start a new burst
        prev = st.copy()
        st['burst_start'] = now
        st['cooldown_until'] = None
        return True, prev, None

async def _rollback_state(guild_id: int, prev_snapshot: Dict[str, Optional[float]]):
    """Rollback per-guild state to prev_snapshot; used if a send fails after starting a new burst."""
    async with _state_lock:
        _state[guild_id] = prev_snapshot

# ---------- Sending ----------

async def _send_to_guild(guild: discord.Guild, content: str):
    now = time.time()

    allow, prev_snapshot, remaining = await _should_send_and_update(guild.id, now)
    if not allow:
        hrs = remaining / 3600 if remaining else 0.0
        log(f"[{guild.name}] In cooldown; skipping. ~{hrs:.2f}h remaining.")
        return

    ch = await _named_sendable_channel(guild, ALERT_CHANNEL_NAME)
    if not ch:
        log(f"[{guild.name}] No send permission to a channel named '#{ALERT_CHANNEL_NAME}'. Skipping.")
        # If we just started a new burst for this message but couldn't send, roll state back
        if prev_snapshot is not None:
            await _rollback_state(guild.id, prev_snapshot)
        return

    role = _find_role_by_name(guild)
    prefix = f"{role.mention} " if role else ""
    allowed_mentions = discord.AllowedMentions(roles=True, users=False, everyone=False)

    try:
        await ch.send(f"{prefix}{content}", allowed_mentions=allowed_mentions)
        # If the burst just started, we don't force-start cooldown now; it begins after BURST_SECONDS
        # (Next messages within the window will send; after the window, cooldown applies automatically.)
        if prev_snapshot is not None:
            log(f"[{guild.name}] Sent to #{ch.name}. (Burst window {BURST_MINUTES:g}m active; cooldown {COOLDOWN_HOURS:g}h after)")
        else:
            # Message sent within an existing burst
            pass
    except Exception as e:
        log(f"[{guild.name}] ERROR sending message: {e}")
        # Roll back starting a burst if send failed
        if prev_snapshot is not None:
            await _rollback_state(guild.id, prev_snapshot)

# ---------- Dispatch & lifecycle ----------

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
    log(f"Burst window: {BURST_MINUTES:g} minutes; Cooldown after burst: {COOLDOWN_HOURS:g} hours")

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
