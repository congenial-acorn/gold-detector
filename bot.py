import os
import asyncio
import threading
from typing import Optional

import discord
from dotenv import load_dotenv

import gold  # gold.py must be importable (same folder or on PYTHONPATH)

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")
ROLE_NAME = os.getenv("ROLE_NAME", "").strip()
BOT_VERBOSE = os.getenv("BOT_VERBOSE", "1") == "1"

intents = discord.Intents.default()
intents.guilds = True  # we only need guild info to find channels
client = discord.Client(intents=intents)

queue: asyncio.Queue[str] = asyncio.Queue()

def log(*a):
    if BOT_VERBOSE:
        print(*a, flush=True)

async def _first_sendable_channel(guild: discord.Guild) -> Optional[discord.TextChannel]:
    """Return the first text channel (by position, then id) the bot can view & send to."""
    for ch in sorted(guild.text_channels, key=lambda c: (c.position, c.id)):
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

async def _send_to_guild(guild: discord.Guild, content: str):
    ch = await _first_sendable_channel(guild)
    if not ch:
        log(f"[{guild.name}] No sendable channel found; skipping.")
        return

    role = _find_role_by_name(guild)
    prefix = f"{role.mention} " if role else ""
    allowed = discord.AllowedMentions(roles=True, users=False, everyone=False)
    await ch.send(f"{prefix}{content}", allowed_mentions=allowed)

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
            log("WARNING: gold.py lacks set_emitter()/send_to_discord(); add the shim shown earlier.")

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

    # Start dispatcher that relays messages to all guilds
    asyncio.create_task(_dispatcher_loop())

if __name__ == "__main__":
    if not TOKEN:
        raise SystemExit("Missing DISCORD_TOKEN in .env")
    client.run(TOKEN)
