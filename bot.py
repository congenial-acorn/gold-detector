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
DEFAULT_ALERT_CHANNEL_NAME = "market-watch"
DEFAULT_ROLE_NAME = "Market Alert"

ALERT_CHANNEL_NAME = os.getenv("ALERT_CHANNEL_NAME", "").strip()
ROLE_NAME = os.getenv("ROLE_NAME", "").strip()
BOT_VERBOSE = os.getenv("BOT_VERBOSE", "1") == "1"


# DEBUG_MODE setup to limit the bot to a specific server
DEBUG_MODE = os.getenv("DEBUG_MODE", "False") == "True"  # Enable/disable debug mode
if DEBUG_MODE:
    DEBUG_SERVER_ID = int(
        os.getenv("DEBUG_SERVER_ID", "0")
    )  # Specify server ID for debug mode
# DEBUG_MODE for DMs
DEBUG_MODE_DMS = os.getenv("DEBUG_MODE_DMS", "False") == "True"
if DEBUG_MODE_DMS:
    DEBUG_USER_ID = int(os.getenv("DEBUG_USER_ID", "0"))

COOLDOWN_HOURS = float(os.getenv("COOLDOWN_HOURS", 48.0))
COOLDOWN_SECONDS = int(COOLDOWN_HOURS * 3600)

HELP_URL = "https://github.com/congenial-acorn/gold-detector/tree/main?tab=readme-ov-file#commands"

_sent_since_last_loop = False


def log(*a):
    if BOT_VERBOSE:
        print(*a, flush=True)


if not TOKEN:
    raise SystemExit("Missing DISCORD_TOKEN in .env")


def _sanitize_channel_name(s: str) -> str:
    return (s or "").strip().lstrip("#")


def _sanitize_role_name(s: str) -> str:
    return (s or "").strip().lstrip("@")


# Per-guild preferences (IDs + display names)
GUILD_PREFS_FILE = Path(__file__).with_name("guild_prefs.json")


# {
#   "<guild_id>": {
#       "channel_id": 123, "channel_name": "market-watch",
#       "role_id": 456,    "role_name": "Market Alert"
#   }
# }
def _load_guild_prefs() -> dict[int, dict]:
    try:
        with open(GUILD_PREFS_FILE, "r", encoding="utf-8") as f:
            raw = json.load(f)
        out: dict[int, dict] = {}
        for gid_str, vals in raw.items():
            out[int(gid_str)] = {
                "channel_id": vals.get("channel_id"),
                "channel_name": (
                    _sanitize_channel_name(vals.get("channel_name"))
                    if vals.get("channel_name")
                    else None
                ),
                "role_id": vals.get("role_id"),
                "role_name": (
                    _sanitize_role_name(vals.get("role_name"))
                    if vals.get("role_name")
                    else None
                ),
            }
        return out
    except Exception:
        return {}


def _save_guild_prefs(p: dict[int, dict]):
    try:
        serial = {str(gid): vals for gid, vals in p.items()}
        with open(GUILD_PREFS_FILE, "w", encoding="utf-8") as f:
            json.dump(serial, f, indent=2, sort_keys=True)
    except Exception as e:
        log(f"[guild-prefs] save error: {e}")


_guild_prefs: dict[int, dict] = _load_guild_prefs()


def _get_effective_channel_name(guild_id: int) -> str:
    prefs = _guild_prefs.get(guild_id) or {}
    name = prefs.get("channel_name") or ALERT_CHANNEL_NAME or DEFAULT_ALERT_CHANNEL_NAME
    return _sanitize_channel_name(name)


def _get_effective_role_name(guild_id: int) -> str:
    prefs = _guild_prefs.get(guild_id) or {}
    name = prefs.get("role_name") or ROLE_NAME or DEFAULT_ROLE_NAME
    return _sanitize_role_name(name)


def _get_effective_channel_id(guild_id: int):
    prefs = _guild_prefs.get(guild_id) or {}
    cid = prefs.get("channel_id")
    return int(cid) if isinstance(cid, (int, str)) and str(cid).isdigit() else None


def _get_effective_role_id(guild_id: int):
    prefs = _guild_prefs.get(guild_id) or {}
    rid = prefs.get("role_id")
    return int(rid) if isinstance(rid, (int, str)) and str(rid).isdigit() else None


intents = discord.Intents.default()
intents.guilds = True
client = discord.Client(intents=intents)

queue: asyncio.Queue[str] = asyncio.Queue()
ping_queue: asyncio.Queue[bool] = asyncio.Queue()

# Per-server and per-message cooldown state


# --- Cooldown persistence (server+DM) ---
SERVER_CD_FILE = Path(__file__).with_name("server_cooldowns.json")
USER_CD_FILE = Path(__file__).with_name("user_cooldowns.json")


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
            serial = {
                str(g): {str(mid): ts for mid, ts in inner.items()}
                for g, inner in m.items()
            }
            json.dump(serial, f)
    except Exception as e:
        log(f"[cooldowns] save error {path.name}: {e}")


def _load_nested_cooldowns(path: Path) -> Dict[int, Dict[int, float]]:
    try:
        with open(path, "r") as f:
            raw = json.load(f)
        # back to ints
        return {
            int(g): {int(mid): float(ts) for mid, ts in inner.items()}
            for g, inner in raw.items()
        }
    except Exception:
        return {}


_server_message_cooldowns: Dict[int, Dict[int, float]] = _load_nested_cooldowns(
    SERVER_CD_FILE
)
_user_message_cooldowns: Dict[int, Dict[int, float]] = _load_nested_cooldowns(
    USER_CD_FILE
)

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
        await interaction.response.send_message(
            "You’re subscribed to DMs. (If you didn’t get a DM, check your privacy settings.)",
            ephemeral=True,
        )
    except Exception as e:
        await interaction.response.send_message(
            f"Couldn’t subscribe: {e}", ephemeral=True
        )


@tree.command(name="alerts_off", description="Stop DMs")
@app_commands.checks.cooldown(1, 5)
async def alerts_off(interaction: discord.Interaction):
    try:
        user_id = interaction.user.id
        _dm_subscribers.discard(user_id)
        _save_subs(_dm_subscribers)
        await interaction.response.send_message(
            "You’re unsubscribed. No more DMs.", ephemeral=True
        )
    except Exception as e:
        await interaction.response.send_message(
            f"Couldn’t unsubscribe: {e}", ephemeral=True
        )


# Optional: a simple /ping that works in DMs too
@tree.command(name="ping", description="Check if the bot is alive")
async def ping_cmd(interaction: discord.Interaction):
    await interaction.response.send_message("Pong!", ephemeral=True)


@app_commands.guild_only()
@app_commands.default_permissions(manage_guild=True)
@tree.command(
    name="server_alerts_off",
    description="Opt this server OUT of alerts (default is ON)",
)
async def server_alerts_off(interaction: discord.Interaction):
    if not interaction.guild:
        return await interaction.response.send_message(
            "Run this in a server.", ephemeral=True
        )
    _guild_optout.add(interaction.guild.id)
    _save_guild_optout(_guild_optout)
    await interaction.response.send_message(
        "🚫 This server is now opted OUT of alerts.", ephemeral=True
    )


@app_commands.guild_only()
@app_commands.default_permissions(manage_guild=True)
@tree.command(name="server_alerts_on", description="Opt this server back IN to alerts")
async def server_alerts_on(interaction: discord.Interaction):
    if not interaction.guild:
        return await interaction.response.send_message(
            "Run this in a server.", ephemeral=True
        )
    _guild_optout.discard(interaction.guild.id)
    _save_guild_optout(_guild_optout)
    await interaction.response.send_message(
        "✅ This server is now opted IN to alerts (default).", ephemeral=True
    )


@app_commands.guild_only()
@app_commands.default_permissions(manage_guild=True)
@tree.command(
    name="set_alert_channel",
    description="Set which channel the bot should post alerts to",
)
@app_commands.describe(channel="Pick a text channel the bot can post in")
async def set_alert_channel(
    interaction: discord.Interaction, channel: discord.TextChannel
):
    if not interaction.guild:
        return await interaction.response.send_message(
            "Run this in a server.", ephemeral=True
        )
    prefs = _guild_prefs.get(interaction.guild.id) or {}
    prefs["channel_id"] = int(channel.id)
    prefs["channel_name"] = _sanitize_channel_name(channel.name)
    _guild_prefs[interaction.guild.id] = prefs
    _save_guild_prefs(_guild_prefs)
    await interaction.response.send_message(
        f"✅ Alerts will go to **#{channel.name}**.", ephemeral=True
    )


@app_commands.guild_only()
@app_commands.default_permissions(manage_guild=True)
@tree.command(
    name="clear_alert_channel",
    description="Revert the alert channel to the default (#market-watch)",
)
async def clear_alert_channel(interaction: discord.Interaction):
    if not interaction.guild:
        return await interaction.response.send_message(
            "Run this in a server.", ephemeral=True
        )
    prefs = _guild_prefs.get(interaction.guild.id) or {}
    prefs.pop("channel_id", None)
    prefs.pop("channel_name", None)
    _guild_prefs[interaction.guild.id] = prefs
    _save_guild_prefs(_guild_prefs)
    await interaction.response.send_message(
        "♻️ Alert channel cleared. Using default: **#market-watch**.", ephemeral=True
    )


@app_commands.guild_only()
@app_commands.default_permissions(manage_guild=True)
@tree.command(
    name="set_alert_role",
    description="Set which role gets pinged when a scan cycle finishes",
)
@app_commands.describe(role="Pick the role to mention")
async def set_alert_role(interaction: discord.Interaction, role: discord.Role):
    if not interaction.guild:
        return await interaction.response.send_message(
            "Run this in a server.", ephemeral=True
        )
    prefs = _guild_prefs.get(interaction.guild.id) or {}
    prefs["role_id"] = int(role.id)
    prefs["role_name"] = _sanitize_role_name(role.name)
    _guild_prefs[interaction.guild.id] = prefs
    _save_guild_prefs(_guild_prefs)
    await interaction.response.send_message(
        f"✅ Will ping **@{role.name}** at the end of each scan.", ephemeral=True
    )


@app_commands.guild_only()
@app_commands.default_permissions(manage_guild=True)
@tree.command(
    name="clear_alert_role",
    description="Revert the ping role to the default (@Market Alert)",
)
async def clear_alert_role(interaction: discord.Interaction):
    if not interaction.guild:
        return await interaction.response.send_message(
            "Run this in a server.", ephemeral=True
        )
    prefs = _guild_prefs.get(interaction.guild.id) or {}
    prefs.pop("role_id", None)
    prefs.pop("role_name", None)
    _guild_prefs[interaction.guild.id] = prefs
    _save_guild_prefs(_guild_prefs)
    await interaction.response.send_message(
        "♻️ Ping role cleared. Using default: **@Market Alert**.", ephemeral=True
    )


@tree.command(
    name="show_alert_settings",
    description="Show this server’s current alert channel/role (with defaults)",
)
async def show_alert_settings(interaction: discord.Interaction):
    if not interaction.guild:
        return await interaction.response.send_message(
            "Run this in a server.", ephemeral=True
        )
    gid = interaction.guild.id
    ch_name = _get_effective_channel_name(gid)
    role_name = _get_effective_role_name(gid)
    cid = _get_effective_channel_id(gid)
    rid = _get_effective_role_id(gid)
    prefs = _guild_prefs.get(gid) or {}
    ch_src = (
        "custom" if prefs.get("channel_id") or prefs.get("channel_name") else "default"
    )
    role_src = "custom" if prefs.get("role_id") or prefs.get("role_name") else "default"
    where = f"<#{cid}>" if cid else f"#{ch_name}"
    who = f"<@&{rid}>" if rid else f"@{role_name}"
    await interaction.response.send_message(
        f"**Alert channel:** {where} ({ch_src})\n**Ping role:** {who} ({role_src})",
        ephemeral=True,
    )

@tree.command(name="help", description="Show help & commands for this bot")
async def help_cmd(interaction: discord.Interaction):
    await interaction.response.send_message(
        f"Gold Detector commands & docs: <{HELP_URL}>",
        ephemeral=True  # set to False if you want it public
        )

@tree.error
async def on_app_command_error(interaction: discord.Interaction, error: Exception):
    from discord.app_commands import CommandOnCooldown

    try:
        if isinstance(error, CommandOnCooldown):
            retry = int(error.retry_after)
            msg = f"⏳ Slow down—try again in ~{retry}s."
            if interaction.response.is_done():
                await interaction.followup.send(msg, ephemeral=True)
            else:
                await interaction.response.send_message(msg, ephemeral=True)
            return
    except Exception:
        pass
    # fall back to default behaviour
    raise error



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

    await asyncio.gather(
        *[asyncio.create_task(_send_one(uid)) for uid in targets],
        return_exceptions=True,
    )


async def _dm_should_send_and_update(user_id: int, message_id: int, now: float):
    """
    Decide if we should DM this user for this specific message.
    Returns (allow: bool, prev_ts: Optional[float], remaining_seconds: Optional[float]).
    """
    # DM debug gate (optional)
    if DEBUG_MODE_DMS and DEBUG_USER_ID and user_id != DEBUG_USER_ID:
        log(
            f"[DEBUG DM] Skipping DM to user {user_id}; only sending to {DEBUG_USER_ID}."
        )
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


def _resolve_sendable_channel(guild: discord.Guild) -> Optional[discord.TextChannel]:
    name = _get_effective_channel_name(guild.id).lower()
    cid = _get_effective_channel_id(guild.id)

    me = getattr(guild, "me", None) or guild.get_member(getattr(client.user, "id", 0))

    # 1) Try explicit ID
    if cid:
        ch = guild.get_channel(cid)
        if isinstance(ch, discord.TextChannel):
            perms = ch.permissions_for(me or guild.default_role)
            if perms.view_channel and perms.send_messages:
                return ch

    # 2) Fallback to name match
    for ch in sorted(guild.text_channels, key=lambda c: (c.position, c.id)):
        if ch.name.lower() == name:
            perms = ch.permissions_for(me or guild.default_role)
            if perms.view_channel and perms.send_messages:
                return ch

    return None


def _find_role_by_name(guild: discord.Guild) -> Optional[discord.Role]:
    """Resolve role by ID first, then by name (per-guild prefs -> env -> default)."""
    rid = _get_effective_role_id(guild.id)
    rname = (
        _get_effective_role_name(guild.id).lower()
        if _get_effective_role_name(guild.id)
        else ""
    )
    if rid:
        role = guild.get_role(rid)
        if isinstance(role, discord.Role):
            return role
    for r in guild.roles:
        if r.name.lower() == rname:
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
        return False

    now = time.time()
    guild_id = guild.id

    if DEBUG_MODE and guild_id != DEBUG_SERVER_ID:
        log(
            f"[DEBUG MODE] Skipping message to server {guild_id}, only sending to {DEBUG_SERVER_ID}."
        )
        return False

    allow, prev_timestamp, remaining = await _should_send_and_update(
        guild_id, message_id, now
    )
    if not allow:
        hrs = remaining / 3600 if remaining else 0.0
        log(
            f"[{guild.name}] Cooldown active for message {message_id} in this server; skipping. ~{hrs:.2f}h remaining."
        )
        return False

    ch = _resolve_sendable_channel(guild)
    if not ch:
        log(
            f"[{guild.name}] No sendable channel resolved (id={_get_effective_channel_id(guild.id)}, name='#{_get_effective_channel_name(guild.id)}'). Skipping."
        )
        return False

    allowed_mentions = discord.AllowedMentions(roles=False, users=False, everyone=False)

    try:
        await ch.send(f"{content}", allowed_mentions=allowed_mentions)
        if prev_timestamp is None:
            log(f"[{guild.name}] Sent to #{ch.name}.")
        else:
            log(
                f"[{guild.name}] Sent to #{ch.name}. (Cooldown applied for message {message_id})"
            )
        return True
    except Exception as e:
        log(f"[{guild.name}] ERROR sending message: {e}")
        return False


# ---------- Dispatcher & Lifecycle ----------


async def _send_ping_to_guild(guild: discord.Guild):
    ch = _resolve_sendable_channel(guild)
    if not ch:
        log(
            f"[{guild.name}] No sendable channel resolved (id={_get_effective_channel_id(guild.id)}, name='#{_get_effective_channel_name(guild.id)}') for ping."
        )
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
        await ch.send(
            f"{role.mention} Scan complete. New results above.",
            allowed_mentions=discord.AllowedMentions(
                roles=True, users=False, everyone=False
            ),
        )
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
            guild_tasks = [
                asyncio.create_task(_send_to_guild(g, msg, message_id))
                for g in client.guilds
            ]
            dm_task = asyncio.create_task(
                _dm_subscribers_broadcast(msg, message_id)
            )  # <-- pass id here
            results = await asyncio.gather(
                *(guild_tasks + [dm_task]), return_exceptions=True
            )
            sent_any = any(
                (r is True) for r in results[:-1] if not isinstance(r, Exception)
            )
            if sent_any:
                global _sent_since_last_loop
                _sent_since_last_loop = True
        finally:
            queue.task_done()


@client.event
async def on_ready():
    await client.change_presence(
        activity=discord.Activity(
            type=discord.ActivityType.watching,
            name="for /help"
        ),
        status=discord.Status.online  # or .idle / .dnd / .invisible
    )
    print(f"Logged in as {client.user}")
    log(f"Default channel: #{ALERT_CHANNEL_NAME or DEFAULT_ALERT_CHANNEL_NAME}")
    log(f"Default ping role: @{ROLE_NAME or DEFAULT_ROLE_NAME}")

    if ROLE_NAME:
        log(f"Ping role on cycle complete: @{ROLE_NAME}")
    log(f"Cooldown after each message: {COOLDOWN_HOURS:g} hours")

    # Wire gold.py -> async queues (thread-safe)
    if hasattr(gold, "set_emitter"):
        gold.set_emitter(
            lambda m: client.loop.call_soon_threadsafe(queue.put_nowait, m)
        )
        log("Emitter registered via gold.set_emitter(...)")
    else:
        # fallback monkey-patch if needed
        if hasattr(gold, "send_to_discord") and callable(
            getattr(gold, "send_to_discord")
        ):
            setattr(
                gold,
                "send_to_discord",
                lambda m: client.loop.call_soon_threadsafe(queue.put_nowait, m),
            )
            log("Emitter installed by monkey-patching gold.send_to_discord(...)")

    def _loop_done_handler():
        # Called by gold.py at the end of its cycle
        global _sent_since_last_loop
        if _sent_since_last_loop:
            _sent_since_last_loop = False
            # only now do we surface the ping into the bot's ping loop
            client.loop.call_soon_threadsafe(ping_queue.put_nowait, True)
        else:
            log("Loop done: no guild deliveries in this cycle; suppressing ping.")

    if hasattr(gold, "set_loop_done_emitter"):
        gold.set_loop_done_emitter(_loop_done_handler)
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
                    log(
                        "ERROR: gold.py has no main(); move your __main__ code into a main() function."
                    )
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
    asyncio.create_task(_dispatcher_loop())  # existing message dispatcher
    asyncio.create_task(_ping_dispatcher_loop())  # NEW ping dispatcher


if __name__ == "__main__":
    client.run(TOKEN)
