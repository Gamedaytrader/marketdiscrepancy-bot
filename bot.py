import discord
import asyncio

import os

DISCORD_TOKEN = os.environ.get("DISCORD_TOKEN")
CHANNEL_ID = 1471542780605239358

intents = discord.Intents.default()
client = discord.Client(intents=intents)

@client.event
async def on_ready():
    print(f"Logged in as {client.user}")
    channel = client.get_channel(CHANNEL_ID)
    await channel.send("🤖 Bot is online and ready to monitor market discrepancies.")

client.run(DISCORD_TOKEN)
