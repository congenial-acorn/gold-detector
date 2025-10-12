import os
import time
import asyncio
import threading
from typing import Optional, Dict
from pathlib import Path
import discord
from discord import app_commands, AllowedMentions
from dotenv import load_dotenv, find_dotenv
import gold  # gold.py must be importable (same folder or on PYTHONPATH)
import json
from hashlib import blake2b

def message_key(s: str) -> int:
    # 8-byte digest -> 64-bit int; tiny chance of collision, stable across restarts
    h = blake2b(s.encode("utf-8"), digest_size=8)
    return int.from_bytes(h.digest(), "big")

# Load .env (CWD first, then next to this file)
_ = load_dotenv(find_dotenv())
if not os.getenv("DISCORD_TOKEN"):
    load_dotenv(Path(__file__).with_name(".env"))

TOKEN = os.getenv("DISCORD_TOKEN")
ALERT_CHANNEL_NAME = os.getenv("ALERT_CHANNEL_NAME", "").strip()
ROLE_NAME = os.getenv("ROLE_NAME", "").strip()
BOT_VERBOSE = os.getenv("BOT_VERBOSE", "1") == "1"

# DEBUG_MODE setup to limit the bot to a specific server
DEBUG_MODE = os.getenv("DEBUG_MODE", "False") == "True"  # Enable/disable debug mode
if DEBUG_MODE:
    DEBUG_SERVER_ID = int(os.getenv("DEBUG_SERVER_ID", "0"))  # Specify server ID for debug mode
# DEBUG_MODE for DMs
DEBUG_MODE_DMS = os.getenv("DEBUG_MODE_DMS", "False") == "True"
if DEBUG_MODE_DMS:
    DEBUG_USER_ID = int(os.getenv("DEBUG_USER_ID", "0"))

COOLDOWN_HOURS = float(os.getenv("COOLDOWN_HOURS", 48.0))
COOLDOWN_SECONDS = int(COOLDOWN_HOURS * 3600)

def log(*a):
    if BOT_VERBOSE:
        print(*a, flush=True)

if not TOKEN:
    raise SystemExit("Missing DISCORD_TOKEN in .env")
if not ALERT_CHANNEL_NAME:
    raise SystemExit("ALERT_CHANNEL_NAME is required in .env")

intents = discord.Intents.default()
intents.guilds = True
client = discord.Client(intents=intents)

queue: asyncio.Queue[str] = asyncio.Queue()
ping_queue: asyncio.Queue[bool] = asyncio.Queue()

# Per-server and per-message cooldown state


# --- Cooldown persistence (server+DM) ---
SERVER_CD_FILE = Path(__file__).with_name("server_cooldowns.json")
USER_CD_FILE   = Path(__file__).with_name("user_cooldowns.json")

def _now() -> float:
    return time.time()

def _prune_cooldown_map(m: Dict[int, Dict[int, float]], max_age: float):
    """Remove entries older than max_age seconds."""
    cutoff = _now() - max_age
    remove_guilds = []
    for outer_key, inner in m.items():
        to_del = [k for k, ts in inner.items() if ts < cutoff]
        for k in to_del:
            del inner[k]
        if not inner:
            remove_guilds.append(outer_key)
    for g in remove_guilds:
        del m[g]

def _save_nested_cooldowns(path: Path, m: Dict[int, Dict[int, float]]):
    try:
        with open(path, "w") as f:
            # json requires str keys; convert
            serial = {str(g): {str(mid): ts for mid, ts in inner.items()} for g, inner in m.items()}
            json.dump(serial, f)
    except Exception as e:
        log(f"[cooldowns] save error {path.name}: {e}")

def _load_nested_cooldowns(path: Path) -> Dict[int, Dict[int, float]]:
    try:
        with open(path, "r") as f:
            raw = json.load(f)
        # back to ints
        return {int(g): {int(mid): float(ts) for mid, ts in inner.items()} for g, inner in raw.items()}
    except Exception:
        return {}



_server_message_cooldowns: Dict[int, Dict[int, float]] = _load_nested_cooldowns(SERVER_CD_FILE)
_user_message_cooldowns: Dict[int, Dict[int, float]] = _load_nested_cooldowns(USER_CD_FILE)

# prune anything older than the active cooldown window
_prune_cooldown_map(_server_message_cooldowns, COOLDOWN_SECONDS)
_prune_cooldown_map(_user_message_cooldowns, COOLDOWN_SECONDS)

# DM logic
SUBS_FILE = Path(__file__).with_name("dm_subscribers.json")

# Load/save helpers
def _load_subs() -> set[int]:
    try:
        with open(SUBS_FILE, "r") as f:
            return set(json.load(f))
    except Exception:
        return set()

def _save_subs(subs: set[int]):
    try:
        with open(SUBS_FILE, "w") as f:
            json.dump(sorted(subs), f)
    except Exception as e:
        log(f"[subs] save error: {e}")

# in-memory subscriber set
_dm_subscribers: set[int] = _load_subs()

GUILD_OPTOUT_FILE = Path(__file__).with_name("guild_optout.json")

def _load_guild_optout() -> set[int]:
    try:
        with open(GUILD_OPTOUT_FILE, "r") as f:
            return set(json.load(f))
    except Exception:
        return set()

def _save_guild_optout(s: set[int]):
    try:
        with open(GUILD_OPTOUT_FILE, "w") as f:
            json.dump(sorted(s), f)
    except Exception as e:
        log(f"[guild-optout] save error: {e}")

_guild_optout: set[int] = _load_guild_optout()


# Slash command tree bound to the existing Client
tree = app_commands.CommandTree(client)

# --- Slash commands (usable in DMs too) ---

@tree.command(name="alerts_on", description="DM me future alerts")
@app_commands.checks.cooldown(1, 5)  # simple spam guard
async def alerts_on(interaction: discord.Interaction):
    try:
        user_id = interaction.user.id
        _dm_subscribers.add(user_id)
        _save_subs(_dm_subscribers)
        # ensure we can DM now
        try:
            await interaction.user.send("✅ Subscribed. I’ll DM you future alerts.")
        except Exception:
            # Just in case DMs are blocked; still ack the slash command
            pass
        await interaction.response.send_message("You’re subscribed to DMs. (If you didn’t get a DM, check your privacy settings.)", ephemeral=True)
    except Exception as e:
        await interaction.response.send_message(f"Couldn’t subscribe: {e}", ephemeral=True)

@tree.command(name="alerts_off", description="Stop DMs")
@app_commands.checks.cooldown(1, 5)
async def alerts_off(interaction: discord.Interaction):
    try:
        user_id = interaction.user.id
        _dm_subscribers.discard(user_id)
        _save_subs(_dm_subscribers)
        await interaction.response.send_message("You’re unsubscribed. No more DMs.", ephemeral=True)
    except Exception as e:
        await interaction.response.send_message(f"Couldn’t unsubscribe: {e}", ephemeral=True)

# Optional: a simple /ping that works in DMs too
@tree.command(name="ping", description="Check if the bot is alive")
async def ping_cmd(interaction: discord.Interaction):
    await interaction.response.send_message("Pong!", ephemeral=True)

@tree.command(name="server_alerts_off", description="Opt this server OUT of alerts (default is ON)")
async def server_alerts_off(interaction: discord.Interaction):
    if not interaction.guild:
        return await interaction.response.send_message("Run this in a server.", ephemeral=True)
    _guild_optout.add(interaction.guild.id)
    _save_guild_optout(_guild_optout)
    await interaction.response.send_message("🚫 This server is now opted OUT of alerts.", ephemeral=True)

@tree.command(name="server_alerts_on", description="Opt this server back IN to alerts")
async def server_alerts_on(interaction: discord.Interaction):
    if not interaction.guild:
        return await interaction.response.send_message("Run this in a server.", ephemeral=True)
    _guild_optout.discard(interaction.guild.id)
    _save_guild_optout(_guild_optout)
    await interaction.response.send_message("✅ This server is now opted IN to alerts (default).", ephemeral=True)

# --- helper to DM all subscribers when gold.py emits a message ---

async def _dm_subscribers_broadcast(content: str, message_id: int):
    allowed_mentions = AllowedMentions.none()
    targets = list(_dm_subscribers)
    if not targets:
        return

    now = time.time()

    async def _send_one(uid: int):
        allow, _prev, remaining = await _dm_should_send_and_update(uid, message_id, now)
        if not allow:
            # Optional: log(f"[DM] Skipping user {uid}; ~{remaining/3600:.2f}h remaining for msg {message_id}")
            return
        try:
            user = await client.fetch_user(uid)
            await user.send(content, allowed_mentions=allowed_mentions)
        except Exception as e:
            # If user can’t be DMed, optionally prune them
            if "Cannot send messages to this user" in str(e):
                _dm_subscribers.discard(uid)
                _save_subs(_dm_subscribers)

    await asyncio.gather(*[asyncio.create_task(_send_one(uid)) for uid in targets],
                         return_exceptions=True)

async def _dm_should_send_and_update(user_id: int, message_id: int, now: float):
    """
    Decide if we should DM this user for this specific message.
    Returns (allow: bool, prev_ts: Optional[float], remaining_seconds: Optional[float]).
    """
    # DM debug gate (optional)
    if DEBUG_MODE_DMS and DEBUG_USER_ID and user_id != DEBUG_USER_ID:
        log(f"[DEBUG DM] Skipping DM to user {user_id}; only sending to {DEBUG_USER_ID}.")
        return False, None, None  # keep the return shape consistent

    d = _user_message_cooldowns.get(user_id)
    if d is None:
        d = {}
        _user_message_cooldowns[user_id] = d

    prev = d.get(message_id)
    if prev is None or (now - prev) >= COOLDOWN_SECONDS:
        d[message_id] = now
        return True, prev, None

    return False, prev, COOLDOWN_SECONDS - (now - prev)

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
    """Return a role by case-insensitive name, or None if not found."""
    if not ROLE_NAME:
        return None
    target = ROLE_NAME.lower()
    for r in guild.roles:
        if r.name.lower() == target:
            return r
    return None

# ---------- Per-server and per-message cooldown logic ----------

async def _should_send_and_update(guild_id: int, message_id: int, now: float):
    """Check and update cooldown for a specific message in a specific server."""
    if guild_id not in _server_message_cooldowns:
        _server_message_cooldowns[guild_id] = {}

    prev_timestamp = _server_message_cooldowns[guild_id].get(message_id)

    if prev_timestamp is None or now - prev_timestamp >= COOLDOWN_SECONDS:
        _server_message_cooldowns[guild_id][message_id] = now
        return True, prev_timestamp, None
    else:
        remaining_time = COOLDOWN_SECONDS - (now - prev_timestamp)
        return False, prev_timestamp, remaining_time

# ---------- Sending ----------

async def _send_to_guild(guild: discord.Guild, content: str, message_id: int):
    if guild.id in _guild_optout:
        return
    now = time.time()
    guild_id = guild.id

    if DEBUG_MODE and guild_id != DEBUG_SERVER_ID:
        log(f"[DEBUG MODE] Skipping message to server {guild_id}, only sending to {DEBUG_SERVER_ID}.")
        return  # Skip sending if not the debug server

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
    allowed_mentions = discord.AllowedMentions(roles=False, users=False, everyone=False)

    try:
        await ch.send(f"{content}", allowed_mentions=allowed_mentions)
        if prev_timestamp is None:
            log(f"[{guild.name}] Sent to #{ch.name}.")
        else:
            log(f"[{guild.name}] Sent to #{ch.name}. (Cooldown applied for message {message_id})")
    except Exception as e:
        log(f"[{guild.name}] ERROR sending message: {e}")

# ---------- Dispatcher & Lifecycle ----------

async def _send_ping_to_guild(guild: discord.Guild):
    ch = await _named_sendable_channel(guild, ALERT_CHANNEL_NAME)
    if not ch:
        log(f"[{guild.name}] No send permission to a channel named '#{ALERT_CHANNEL_NAME}' for ping.")
        return

    role = _find_role_by_name(guild)
    if not role:
        # If there’s no role configured/found, send a plain “cycle complete” note without ping
        try:
            await ch.send("Scan complete. New results above.")
        except Exception as e:
            log(f"[{guild.name}] ERROR sending ping fallback: {e}")
        return

    # Ping the role once per cycle
    try:
        await ch.send(f"{role.mention} Scan complete. New results above.",
                      allowed_mentions=discord.AllowedMentions(roles=True, users=False, everyone=False))
        log(f"[{guild.name}] Sent cycle-complete ping to #{ch.name}")
    except Exception as e:
        log(f"[{guild.name}] ERROR sending ping: {e}")

async def _ping_dispatcher_loop():
    await client.wait_until_ready()
    while True:
        _ = await ping_queue.get()  # value is unused; presence is the signal
        try:
            tasks = [asyncio.create_task(_send_ping_to_guild(g)) for g in client.guilds]
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
        finally:
            ping_queue.task_done()

async def _dispatcher_loop():
    await client.wait_until_ready()
    while True:
        msg = await queue.get()
        message_id = message_key(msg)  # same id used for guild cooldowns
        try:
            guild_tasks = [asyncio.create_task(_send_to_guild(g, msg, message_id)) for g in client.guilds]
            dm_task = asyncio.create_task(_dm_subscribers_broadcast(msg, message_id))  # <-- pass id here
            await asyncio.gather(*(guild_tasks + [dm_task]), return_exceptions=True)
        finally:
            queue.task_done()

@client.event
async def on_ready():
    log(f"✅ Logged in as {client.user} (id={client.user.id})")
    log(f"Posting only to channels named: #{ALERT_CHANNEL_NAME}")



    if ROLE_NAME:
        log(f"Ping role on cycle complete: @{ROLE_NAME}")
    log(f"Cooldown after each message: {COOLDOWN_HOURS:g} hours")

    # Wire gold.py -> async queues (thread-safe)
    if hasattr(gold, "set_emitter"):
        gold.set_emitter(lambda m: client.loop.call_soon_threadsafe(queue.put_nowait, m))
        log("Emitter registered via gold.set_emitter(...)")
    else:
        # fallback monkey-patch if needed
        if hasattr(gold, "send_to_discord") and callable(getattr(gold, "send_to_discord")):
            setattr(gold, "send_to_discord", lambda m: client.loop.call_soon_threadsafe(queue.put_nowait, m))
            log("Emitter installed by monkey-patching gold.send_to_discord(...)")

    if hasattr(gold, "set_loop_done_emitter"):
        gold.set_loop_done_emitter(lambda: client.loop.call_soon_threadsafe(ping_queue.put_nowait, True))
        log("Loop-done emitter registered via gold.set_loop_done_emitter(...)")
    async def _cooldown_snapshot_loop():
        while True:
            _prune_cooldown_map(_server_message_cooldowns, COOLDOWN_SECONDS)
            _prune_cooldown_map(_user_message_cooldowns, COOLDOWN_SECONDS)
            _save_nested_cooldowns(SERVER_CD_FILE, _server_message_cooldowns)
            _save_nested_cooldowns(USER_CD_FILE, _user_message_cooldowns)
            await asyncio.sleep(60)
    try:
        # make slash commands available globally (works in DMs if dm_permission=True)
        await tree.sync()
        log("Slash commands synced.")
    except Exception as e:
        log(f"Slash command sync failed: {e}")

    # Start gold.py forever (your existing code with backoff)
    def run_gold_forever():
        max_backoff = 3600
        base = 5
        backoff = base
        while True:
            try:
                if hasattr(gold, "main") and callable(getattr(gold, "main")):
                    gold.main()
                    backoff = base
                else:
                    log("ERROR: gold.py has no main(); move your __main__ code into a main() function.")
                    break
            except KeyboardInterrupt:
                raise
            except BaseException as e:
                s = str(e)
                if "429" in s:
                    log(f"[gold.py] 429; restarting in {backoff}s...")
                else:
                    log(f"[gold.py] crashed: {e}; restarting in {backoff}s...")
                time.sleep(backoff)
                backoff = min(backoff * 2, max_backoff)

    threading.Thread(target=run_gold_forever, name="gold-runner", daemon=True).start()
    log("Started gold.py in background thread.")

    # Start dispatchers
    asyncio.create_task(_cooldown_snapshot_loop())
    asyncio.create_task(_dispatcher_loop())       # existing message dispatcher
    asyncio.create_task(_ping_dispatcher_loop())  # NEW ping dispatcher

if __name__ == "__main__":
    client.run(TOKEN)

