import discord
import asyncio
import requests
import os

DISCORD_TOKEN = os.environ.get("DISCORD_TOKEN")
CHANNEL_ID = 1471542780605239358  # keep your channel ID

intents = discord.Intents.default()
client = discord.Client(intents=intents)

POLYMARKET_URL = "https://clob.polymarket.com/markets"

async def fetch_polymarket():
    try:
        r = requests.get(POLYMARKET_URL, timeout=10)
        r.raise_for_status()
        payload = r.json()
        return payload.get("data", [])
    except Exception as e:
        print(f"[Polymarket] Error fetching data: {e}")
        return []


async def polymarket_loop():
    await client.wait_until_ready()
    while not client.is_closed():
        markets = await fetch_polymarket()

        print(f"\n[Polymarket] Pulled {len(markets)} markets")

        # Log a few sample markets so we know it works
        for m in markets[:5]:
            question = m.get("question")
            yes_price = m.get("yes_price")
            liquidity = m.get("liquidity")

            print(
                f"[Polymarket] {question} | YES: {yes_price} | Liquidity: {liquidity}"
            )

        # wait 10 minutes
        await asyncio.sleep(600)

@client.event
async def on_ready():
    print(f"Logged in as {client.user}")
    client.loop.create_task(polymarket_loop())

client.run(DISCORD_TOKEN)
