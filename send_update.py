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
            json.dump(sorted(subs
