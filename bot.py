import os
import sys
import asyncio
import discord
from dotenv import load_dotenv

load_dotenv()
TOKEN = os.getenv("DISCORD_BOT_TOKEN")
SCRIPT_PATH = os.getenv("SCRIPT_PATH", "gold.py")

if not TOKEN:
    raise SystemExit("Missing DISCORD_BOT_TOKEN in .env")
if not os.path.exists(SCRIPT_PATH):
    print(f"Warning: SCRIPT_PATH not found: {SCRIPT_PATH}")

# Minimal intents: we just need to know the guilds and send messages.
intents = discord.Intents.none()
intents.guilds = True

client = discord.Client(intents=intents)

# guild_id -> channel object where we can send
targets: dict[int, discord.abc.Messageable] = {}

def pick_channel(guild: discord.Guild):
    """Prefer system channel; otherwise first text channel we can send in."""
    me = guild.me
    def can_send(ch: discord.TextChannel):
        try:
            perms = ch.permissions_for(me)
            return perms.send_messages
        except Exception:
            return False

    if guild.system_channel and can_send(guild.system_channel):
        return guild.system_channel
    for ch in guild.text_channels:
        if can_send(ch):
            return ch
    return None

async def refresh_targets():
    """Populate targets for all guilds we’re in."""
    for g in client.guilds:
        if g.id not in targets or targets[g.id] is None:
            ch = pick_channel(g)
            if ch:
                targets[g.id] = ch
                try:
                    await ch.send("👋 Streaming script output here.")
                except Exception:
                    pass
            else:
                print(f"[warn] No sendable channel in {g.name} ({g.id})")

async def broadcast(text: str):
    """Send a single line to all target channels (truncate to 2000 chars)."""
    if not text:
        return
    msg = text[:2000]
    for ch in list(targets.values()):
        try:
            await ch.send(msg)
        except Exception:
            # ignore missing perms / HTTP issues in minimal bot
            pass

async def run_and_stream():
    """Run SCRIPT_PATH with unbuffered Python; stream stdout & stderr line-by-line."""
    while True:
        try:
            proc = await asyncio.create_subprocess_exec(
                sys.executable, "-u", SCRIPT_PATH,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env={**os.environ, "PYTHONUNBUFFERED": "1"},
            )
            await broadcast(f"▶️ Started `{os.path.basename(SCRIPT_PATH)}`")
        except Exception as e:
            await broadcast(f"❌ Failed to start script: {e}. Retrying in 5s…")
            await asyncio.sleep(5)
            continue

        async def pump(stream: asyncio.StreamReader, label: str):
            while True:
                line = await stream.readline()
                if not line:
                    break
                text = line.decode(errors="replace").rstrip("\r\n")
                # Prefix with [stdout]/[stderr] so people can tell which is which
                await broadcast(f"[{label}] {text}")

        # Pump both streams; wait for process to exit
        await asyncio.gather(
            pump(proc.stdout, "stdout"),
            pump(proc.stderr, "stderr"),
        )

        await broadcast("⏹️ Script stopped. Restarting in 5s…")
        await asyncio.sleep(5)

@client.event
async def on_ready():
    print(f"Logged in as {client.user}")
    await refresh_targets()
    # Start the stream loop
    client.loop.create_task(run_and_stream())

@client.event
async def on_guild_join(guild: discord.Guild):
    ch = pick_channel(guild)
    if ch:
        targets[guild.id] = ch
        try:
            await ch.send("👋 Thanks for inviting me — I’ll post script output here.")
        except Exception:
            pass
    else:
        print(f"[warn] Joined {guild.name} but no channel I can send to.")

def main():
    client.run(TOKEN)

if __name__ == "__main__":
    main()
