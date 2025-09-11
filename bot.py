import os
import sys
import asyncio
import discord
from dotenv import load_dotenv

load_dotenv()
TOKEN = os.getenv("DISCORD_BOT_TOKEN")
SCRIPT_PATH = os.getenv("SCRIPT_PATH", "scripts/gold.py")
PREFIX = os.getenv("DISCORD_PREFIX", "__DISCORD__")
FORWARD_ALL = os.getenv("FORWARD_ALL", "false").lower() in ("1","true","yes")

if not TOKEN:
    raise SystemExit("Missing DISCORD_BOT_TOKEN in .env")

intents = discord.Intents.none()
intents.guilds = True
client = discord.Client(intents=intents)

targets: dict[int, discord.abc.Messageable] = {}

def pick_channel(guild: discord.Guild):
    me = guild.me
    def can_send(ch: discord.TextChannel):
        try: return ch.permissions_for(me).send_messages
        except: return False
    if guild.system_channel and can_send(guild.system_channel):
        return guild.system_channel
    for ch in guild.text_channels:
        if can_send(ch):
            return ch
    return None

async def refresh_targets():
    for g in client.guilds:
        if g.id not in targets or targets[g.id] is None:
            ch = pick_channel(g)
            if ch:
                targets[g.id] = ch

async def safe_send(ch: discord.abc.Messageable, text: str):
    if not text: return
    # chunk to <=2000 chars
    for i in range(0, len(text), 2000):
        try: await ch.send(text[i:i+2000])
        except: pass

async def broadcast(text: str):
    await refresh_targets()
    await asyncio.gather(*(safe_send(ch, text) for ch in targets.values()))

async def run_and_stream():
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
            await asyncio.sleep(5); continue

        async def pump(stream: asyncio.StreamReader, label: str):
            while True:
                line = await stream.readline()
                if not line:
                    break
                text = line.decode(errors="replace").rstrip("\r\n")
                if FORWARD_ALL:
                    await broadcast(f"[{label}] {text}")
                else:
                    # Only forward lines that start with PREFIX
                    if text.startswith(PREFIX):
                        await broadcast(text[len(PREFIX):].lstrip())

        await asyncio.gather(pump(proc.stdout, "stdout"), pump(proc.stderr, "stderr"))
        await broadcast("⏹️ Script stopped. Restarting in 5s…")
        await asyncio.sleep(5)

@client.event
async def on_ready():
    print(f"Logged in as {client.user}")
    await refresh_targets()
    await broadcast(f"🤖 Ready. Forwarding lines starting with `{PREFIX}`.")
    client.loop.create_task(run_and_stream())

@client.event
async def on_guild_join(guild: discord.Guild):
    ch = pick_channel(guild)
    if ch:
        targets[guild.id] = ch
        await safe_send(ch, "👋 Thanks for inviting me! I’ll post marked messages here.")

if __name__ == "__main__":
    client.run(TOKEN)
