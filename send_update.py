import os
import sys
import discord
import asyncio
from discord.ext import commands
from discord import Embed
from pathlib import Path
import json

# Load environment variables
from dotenv import load_dotenv
load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")
ALERT_CHANNEL_NAME = os.getenv("ALERT_CHANNEL_NAME", "")
DM_SUBSCRIBERS_FILE = Path(__file__).with_name("dm_subscribers.json")
GUILD_SUBSCRIBERS_FILE = Path(__file__).with_name("guild_subscribers.json")

# Load the list of subscribers from files
def load_subscribers():
    try:
        with open(DM_SUBSCRIBERS_FILE, "r") as f:
            return set(json.load(f))
    except Exception:
        return set()

def load_guild_subscribers():
    try:
        with open(GUILD_SUBSCRIBERS_FILE, "r") as f:
            return set(json.load(f))
    except Exception:
        return set()

# Save subscribers
def save_subscribers(subs):
    try:
        with open(DM_SUBSCRIBERS_FILE, "w") as f:
            json.dump(sorted(subs), f)
    except Exception as e:
        print(f"Error saving subscribers: {e}")

def save_guild_subscribers(subs):
    try:
        with open(GUILD_SUBSCRIBERS_FILE, "w") as f:
            json.dump(sorted(subs), f)
    except Exception as e:
        print(f"Error saving guild subscribers: {e}")

# Setup Discord bot client
intents = discord.Intents.default()
intents.message_content = True
client = commands.Bot(command_prefix="!", intents=intents)

# --- Send updates to all subscribers (DMs) ---
async def send_update_to_dms(message: str):
    """Send a message to all subscribed users."""
    subscribers = load_subscribers()
    for user_id in subscribers:
        try:
            user = await client.fetch_user(user_id)
            await user.send(message)
            print(f"Sent DM to {user.name}")
        except Exception as e:
            print(f"Could not send DM to user {user_id}: {e}")

# --- Send updates to all servers ---
async def send_update_to_servers(message: str):
    """Send a message to all servers' alert channels."""
    for guild in client.guilds:
        channel = discord.utils.get(guild.text_channels, name=ALERT_CHANNEL_NAME)
        if channel:
            try:
                await channel.send(message)
                print(f"Sent message to #{channel.name} in {guild.name}")
            except Exception as e:
                print(f"Could not send message to {guild.name}: {e}")

# --- CLI function to trigger the update ---
def send_update(message: str, send_to: str):
    """Send an update to either DMs or all servers."""
    if send_to == "dms":
        asyncio.run(send_update_to_dms(message))
    elif send_to == "servers":
        asyncio.run(send_update_to_servers(message))
    else:
        print("Invalid option. Use 'dms' or 'servers'.")

# --- Bot ready event (for CLI execution) ---
@client.event
async def on_ready():
    print(f'Logged in as {client.user} (ID: {client.user.id})')
    # Once the bot is ready, execute the update
    if len(sys.argv) >= 3:
        message = sys.argv[1]
        send_to = sys.argv[2]
        send_update(message, send_to)
        await client.close()

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python send_update.py <message> <dms|servers>")
    else:
        client.run(TOKEN)
