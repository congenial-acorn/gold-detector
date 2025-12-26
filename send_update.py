# send_update.py
import os
import sys
import json
import asyncio
from pathlib import Path

import discord
from dotenv import load_dotenv

load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
ALERT_CHANNEL_NAME = os.getenv("ALERT_CHANNEL_NAME", "").strip()
DEBUG_MODE = os.getenv("DEBUG_MODE", "").strip()
DEBUG_MODE_DMS = os.getenv("DEBUG_MODE_DMS", "").strip()
if DEBUG_MODE:
    DEBUG_SERVER_ID = int(os.getenv("DEBUG_SERVER_ID", "0"))
if DEBUG_MODE_DMS:
    DEBUG_USER_ID = int(os.getenv("DEBUG_USER_ID", "0"))

DM_SUBS_FILE = Path(__file__).with_name("dm_subscribers.json")
# If you use guild opt-out/opt-in files, you can also reference them here as needed.


def load_dm_subs() -> list[int]:
    try:
        with open(DM_SUBS_FILE, "r") as f:
            return list(json.load(f))
    except Exception:
        return []


# ---- sending helpers ---------------------------------------------------------


async def send_update_to_dms(client: discord.Client, message: str):
    subs = load_dm_subs()
    if not subs:
        print("No DM subscribers found.")
        return
    # gentle pacing to avoid rate limits
    for uid in subs:
        try:
            user = await client.fetch_user(int(uid))
            await user.send(
                message,
                allowed_mentions=discord.AllowedMentions.none(),
                suppress_embeds=True,
            )
            print(f"DM sent -> {user.id}")
            await asyncio.sleep(0.5)
        except Exception as e:
            print(f"DM failed -> {uid}: {e}")


async def send_update_to_servers(
    client: discord.Client, message: str, channel_name: str
):
    if not channel_name:
        print("ALERT_CHANNEL_NAME is empty; set it in .env to broadcast to servers.")
        return
    for guild in client.guilds:
        try:
            # first sendable channel matching the name
            target = None
            for ch in sorted(guild.text_channels, key=lambda c: (c.position, c.id)):
                if ch.name.lower() == channel_name.lower():
                    perms = ch.permissions_for(guild.me)
                    if perms.view_channel and perms.send_messages:
                        target = ch
                        break
            if not target:
                print(f"[{guild.name}] no sendable #{channel_name}")
                continue
            await target.send(
                message,
                allowed_mentions=discord.AllowedMentions(
                    roles=False, users=False, everyone=False
                ),
                suppress_embeds=True,
            )
            print(f"[{guild.name}] sent -> #{target.name}")
            await asyncio.sleep(0.5)
        except Exception as e:
            print(f"[{guild.name}] send failed: {e}")


# ---- main client -------------------------------------------------------------

# We do NOT need privileged intents here.
intents = discord.Intents.none()
intents.guilds = True  # we iterate guilds to send to channels
client = discord.Client(intents=intents)


@client.event
async def on_ready():
    print(f"Logged in as {client.user} (ID: {client.user.id})")
    # Parse args when the client is ready
    if len(sys.argv) < 3:
        print('Usage: python send_update.py "message" dms|servers')
        await client.close()
        return

    message = sys.argv[1]
    target = sys.argv[2].lower()

    try:
        if target == "dms":
            await send_update_to_dms(client, message)
        elif target == "servers":
            await send_update_to_servers(client, message, ALERT_CHANNEL_NAME)
        else:
            print("Invalid target. Use 'dms' or 'servers'.")
    finally:
        await client.close()


if __name__ == "__main__":
    if not TOKEN:
        print("Missing DISCORD_TOKEN in environment/.env")
        sys.exit(1)
    # Note: no asyncio.run inside event loop; discord handles it.
    client.run(TOKEN)
