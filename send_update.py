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
def set_emitter(func):
    """Bot calls this to register a simple, thread-safe 'emit(message: str)' function."""
    global _emit
    _emit = func

def send_to_discord(message: str):
    """gold.py will keep calling this. The bot provides the real emitter."""
    if _emit is not None:
        _emit(message)
    else:
        print(f"[Discord] (noop) {message}")  # falls back to stdout if bot not wired

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python send_update.py <message> <dms|servers>")
    else:
        client.run(TOKEN)
