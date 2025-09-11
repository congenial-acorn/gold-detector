import os
import sys
import asyncio
from pathlib import Path

import discord
from dotenv import load_dotenv

# ---------------- Config ----------------
load_dotenv()

def _bool(name: str, default: str = "false") -> bool:
    return os.getenv(name, default).strip().lower() in ("1", "true", "yes", "y", "on")

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

RESTART_DELAY_SECS = 5

# --------------- Discord Client ---------------
intents = discord.Intents.none()
intents.guilds = True  # we only need to know which guilds we're in
client = discord.Client(intents=intents)

# guild_id -> channel to post in
targets: dict[int, discord.abc.Messageable] = {}

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

async def _refresh_targets():
    for g in client.guilds:
        if g.id not in targets or targets[g.id] is None:
            ch = _pick_channel(g)
            if ch:
                targets[g.id] = ch

async def _safe_send(ch: discord.abc.Messageable, text: str):
    if not text:
        return
    # Discord hard limit: 2000 chars
    for i in range(0, len(text), 2000):
        try:
            await ch.send(text[i:i+2000])
        except Exception:
            # ignore permission/rate errors in this minimal bot
            pass

async def _broadcast(text: str):
    await _refresh_targets()
    await asyncio.gather(*(_safe_send(ch, text) for ch in targets.values()))

# --------------- Runner: gold.py ---------------
async def _run_and_stream():
    """Run gold.py unbuffered and forward its output according to rules."""
    # Always show operational info in stdout for debugging
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
                await _broadcast(f"▶️ Started `{SCRIPT_PATH.name}`")
            else:
                print(f"[bot] started {SCRIPT_PATH.name}")
        except Exception as e:
            msg = f"❌ Failed to start script: {e}. Retrying in {RESTART_DELAY_SECS}s…"
            if ANNOUNCE_SYSTEM:
                await _broadcast(msg)
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
                    await _broadcast(f"[{label}] {text}")
                else:
                    if text.startswith(PREFIX):
                        # Strip prefix and any leading whitespace after it
                        await _broadcast(text[len(PREFIX):].lstrip())

        # Read both stdout/stderr concurrently
        await asyncio.gather(
            pump(proc.stdout, "stdout"),
            pump(proc.stderr, "stderr"),
        )

        if ANNOUNCE_SYSTEM:
            await _broadcast(f"⏹️ `{SCRIPT_PATH.name}` exited. Restarting in {RESTART_DELAY_SECS}s…")
        print(f"[bot] process exited; restarting in {RESTART_DELAY_SECS}s…")
        await asyncio.sleep(RESTART_DELAY_SECS)

# --------------- Events ---------------
@client.event
async def on_ready():
    print(f"[bot] logged in as {client.user}")
    await _refresh_targets()
    if ANNOUNCE_SYSTEM:
        await _broadcast(f"🤖 Ready. Forwarding lines starting with `{PREFIX}`.")
    # start the runner
    client.loop.create_task(_run_and_stream())

@client.event
async def on_guild_join(guild: discord.Guild):
    ch = _pick_channel(guild)
    if ch:
        targets[guild.id] = ch
        if ANNOUNCE_SYSTEM:
            await _safe_send(ch, "👋 Thanks for inviting me! I’ll post marked messages here.")

# --------------- Main ---------------
if __name__ == "__main__":
    # Friendly check to help catch path issues
    if not SCRIPT_PATH.exists():
        print(f"[bot] WARNING: Script not found at {SCRIPT_PATH}")
    client.run(TOKEN)
