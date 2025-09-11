import os
import sys
import asyncio
from pathlib import Path

import discord
from discord import AllowedMentions
from dotenv import load_dotenv

# ---------------- Config ----------------
load_dotenv()

def _bool(name: str, default: str = "false") -> bool:
    return os.getenv(name, default).strip().lower() in ("1","true","yes","y","on")

TOKEN = os.getenv("DISCORD_BOT_TOKEN")
if not TOKEN:
    raise SystemExit("Missing DISCORD_BOT_TOKEN in .env")

# Resolve SCRIPT_PATH relative to this file so it works no matter where you run from
_raw_script = os.getenv("SCRIPT_PATH", "scripts/gold.py")
SCRIPT_PATH = Path(_raw_script)
if not SCRIPT_PATH.is_absolute():
    SCRIPT_PATH = (Path(__file__).parent / SCRIPT_PATH).resolve()

PREFIX = os.getenv("DISCORD_PREFIX", "__DISCORD__")
FORWARD_ALL = _bool("FORWARD_ALL", "false")
ANNOUNCE_SYSTEM = _bool("ANNOUNCE_SYSTEM", "false")

# Ping config
PING_ROLE_ID = int(os.getenv("PING_ROLE_ID", "0") or "0")
PING_ROLE_NAME = os.getenv("PING_ROLE_NAME", "")  # fallback if ID not set/found
PING_ALWAYS = _bool("PING_ALWAYS", "false")
PING_TOKEN = os.getenv("PING_TOKEN", "[PING]").strip()

RESTART_DELAY_SECS = 5

# --------------- Discord Client ---------------
intents = discord.Intents.none()
intents.guilds = True  # we only need to know which guilds we're in
client = discord.Client(intents=intents)

# guild_id -> channel to post in
targets: dict[int, discord.abc.Messageable] = {}
# guild_id -> discord.Role (to ping) or None
ping_roles: dict[int, discord.Role | None] = {}

def _pick_channel(guild: discord.Guild):
    """Prefer system channel, else first text channel we can send to."""
    me = guild.me
    def can_send(ch: discord.TextChannel):
        try:
            return ch.permissions_for(me).send_messages
        except Exception:
            return False
    if guild.system_channel and can_send(guild.system_channel):
        return guild.system_channel
    for ch in guild.text_channels:
        if can_send(ch):
            return ch
    return None

def _resolve_ping_role(guild: discord.Guild) -> discord.Role | None:
    # 1) Try explicit role ID
    if PING_ROLE_ID:
        r = guild.get_role(PING_ROLE_ID)
        if r:
            return r
    # 2) Try by name (case-insensitive)
    if PING_ROLE_NAME:
        low = PING_ROLE_NAME.lower()
        for r in guild.roles:
            if r.name.lower() == low:
                return r
    return None

async def _refresh_targets_and_roles():
    for g in client.guilds:
        # choose a channel
        if g.id not in targets or targets[g.id] is None:
            ch = _pick_channel(g)
            if ch:
                targets[g.id] = ch

        # resolve role
        role = _resolve_ping_role(g)
        ping_roles[g.id] = role

        # one-line debug so you can see what the bot found
        try:
            print(
                f"[ping-debug] guild={g.name}({g.id}) "
                f"channel={getattr(targets.get(g.id), 'name', None)} "
                f"role={'None' if role is None else f'{role.name}({role.id})'} "
                f"role_mentionable={'-' if role is None else role.mentionable} "
                f"bot_can_mention_all={g.me.guild_permissions.mention_everyone}"
            )
        except Exception:
            pass

async def _safe_send(ch: discord.abc.Messageable, text: str, *, allow_role_mentions: bool = False):
    if not text:
        return
    # Discord hard limit: 2000 chars. We pass AllowedMentions per-send.
    am = AllowedMentions(roles=allow_role_mentions, users=False, everyone=False)
    for i in range(0, len(text), 2000):
        try:
            await ch.send(text[i:i+2000], allowed_mentions=am)
        except Exception:
            pass

async def _send_with_optional_ping(guild_id: int, text: str, do_ping: bool):
    ch = targets.get(guild_id)
    if not ch or not text:
        return
    role = ping_roles.get(guild_id)
    if do_ping and role is not None:
        mention = role.mention + " "
        # First chunk includes the mention; subsequent chunks are plain.
        first_chunk = text[: (2000 - len(mention))]
        await _safe_send(ch, mention + first_chunk, allow_role_mentions=True)
        rest = text[len(first_chunk):]
        if rest:
            await _safe_send(ch, rest, allow_role_mentions=False)
    else:
        await _safe_send(ch, text, allow_role_mentions=False)

async def _broadcast(text: str, *, do_ping: bool):
    await _refresh_targets_and_roles()
    await asyncio.gather(*(_send_with_optional_ping(gid, text, do_ping) for gid in targets.keys()))

# --------------- Runner: gold.py ---------------
async def _run_and_stream():
    """Run gold.py unbuffered and forward its output according to rules."""
    print(f"[bot] runner watching: {SCRIPT_PATH}")

    while True:
        try:
            proc = await asyncio.create_subprocess_exec(
                sys.executable, "-u", str(SCRIPT_PATH),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env={**os.environ, "PYTHONUNBUFFERED": "1"},
            )
            if ANNOUNCE_SYSTEM:
                await _broadcast(f"▶️ Started `{SCRIPT_PATH.name}`", do_ping=False)
            else:
                print(f"[bot] started {SCRIPT_PATH.name}")
        except Exception as e:
            msg = f"❌ Failed to start script: {e}. Retrying in {RESTART_DELAY_SECS}s…"
            if ANNOUNCE_SYSTEM:
                await _broadcast(msg, do_ping=False)
            print("[bot]", msg)
            await asyncio.sleep(RESTART_DELAY_SECS)
            continue

        async def pump(stream: asyncio.StreamReader, label: str):
            while True:
                line = await stream.readline()
                if not line:
                    break
                text = line.decode(errors="replace").rstrip("\r\n")

                if FORWARD_ALL:
                    # When mirroring all, ping only if token appears at start
                    do_ping = text.startswith(PING_TOKEN)
                    if do_ping:
                        text = text[len(PING_TOKEN):].lstrip()
                    await _broadcast(f"[{label}] {text}", do_ping=do_ping)
                else:
                    # Only forward lines that start with PREFIX
                    if not text.startswith(PREFIX):
                        continue
                    text = text[len(PREFIX):].lstrip()
                    # Per-message ping if the token is present at the start
                    do_ping = text.startswith(PING_TOKEN)
                    if do_ping:
                        text = text[len(PING_TOKEN):].lstrip()
                    # Or always ping if configured
                    do_ping = do_ping or PING_ALWAYS
                    await _broadcast(text, do_ping=do_ping)

        await asyncio.gather(
            pump(proc.stdout, "stdout"),
            pump(proc.stderr, "stderr"),
        )

        if ANNOUNCE_SYSTEM:
            await _broadcast(f"⏹️ `{SCRIPT_PATH.name}` exited. Restarting in {RESTART_DELAY_SECS}s…", do_ping=False)
        print(f"[bot] process exited; restarting in {RESTART_DELAY_SECS}s…")
        await asyncio.sleep(RESTART_DELAY_SECS)

# --------------- Events ---------------
@client.event
async def on_ready():
    print(f"[bot] logged in as {client.user}")
    await _refresh_targets_and_roles()
    if ANNOUNCE_SYSTEM:
        await _broadcast(f"🤖 Ready. Forwarding lines starting with `{PREFIX}`.", do_ping=False)
    client.loop.create_task(_run_and_stream())

@client.event
async def on_guild_join(guild: discord.Guild):
    # Prepare channel/role for this guild
    await _refresh_targets_and_roles()
    ch = targets.get(guild.id)
    if ch and ANNOUNCE_SYSTEM:
        await _safe_send(ch, "👋 Thanks for inviting me! I’ll post marked messages here.", allow_role_mentions=False)

# --------------- Main ---------------
if __name__ == "__main__":
    if not SCRIPT_PATH.exists():
        print(f"[bot] WARNING: Script not found at {SCRIPT_PATH}")
    client.run(TOKEN)
