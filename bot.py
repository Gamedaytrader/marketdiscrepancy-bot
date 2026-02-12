import discord
import asyncio
import aiohttp
import os

DISCORD_TOKEN = os.environ.get("DISCORD_TOKEN")
CHANNEL_ID = 1471542780605239358

POLYMARKET_URL = "https://clob.polymarket.com/markets"
FETCH_INTERVAL = 600  # seconds

intents = discord.Intents.default()
client = discord.Client(intents=intents)


# -------- Polymarket Logic -------- #

async def fetch_polymarket_markets(session):
    try:
        async with session.get(POLYMARKET_URL, timeout=10) as resp:
            resp.raise_for_status()
            payload = await resp.json()
            return payload.get("data", [])
    except Exception as e:
        print(f"[Polymarket] Fetch error: {e}")
        return []


def extract_binary_yes_prob(market):
    outcomes = market.get("outcomes", [])
    if len(outcomes) != 2:
        return None

    for outcome in outcomes:
        if outcome.get("name", "").upper() == "YES":
            bid = outcome.get("bestBid")
            ask = outcome.get("bestAsk")
            if bid is not None and ask is not None:
                return (bid + ask) / 2

    return None


async def polymarket_loop():
    await client.wait_until_ready()

    async with aiohttp.ClientSession() as session:
        while not client.is_closed():
            markets = await fetch_polymarket_markets(session)
            print(f"\n[Polymarket] Pulled {len(markets)} markets")

            shown = 0
            for market in markets:
                prob = extract_binary_yes_prob(market)
                if prob is None:
                    continue

                question = market.get("question", "Unknown market")
                print(f"[Polymarket] {question} | YES ≈ {prob:.2%}")

                shown += 1
                if shown >= 5:
                    break

            await asyncio.sleep(FETCH_INTERVAL)


# -------- Discord Events -------- #

@client.event
async def on_ready():
    print(f"Logged in as {client.user}")
    client.loop.create_task(polymarket_loop())


client.run(DISCORD_TOKEN)

