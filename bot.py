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
       shown = 0

for m in markets:
    outcomes = m.get("outcomes", [])

    # Only binary markets
    if len(outcomes) != 2:
        continue

    yes_outcome = next(
        (o for o in outcomes if o.get("name", "").upper() == "YES"),
        None
    )

    if not yes_outcome:
        continue

    best_bid = yes_outcome.get("bestBid")
    best_ask = yes_outcome.get("bestAsk")

    if best_bid is None or best_ask is None:
        continue

    yes_prob = (best_bid + best_ask) / 2

    print(
        f"[Polymarket] {m.get('question')} | YES ≈ {yes_prob:.2%}"
    )

    shown += 1
    if shown >= 5:
        break


        # wait 10 minutes
        await asyncio.sleep(600)

@client.event
async def on_ready():
    print(f"Logged in as {client.user}")
    client.loop.create_task(polymarket_loop())

client.run(DISCORD_TOKEN)
