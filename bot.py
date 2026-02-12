import discord
import asyncio
import aiohttp
import os

DISCORD_TOKEN = os.environ.get("DISCORD_TOKEN")
CHANNEL_ID = 1471542780605239358

POLYMARKET_URL = "https://clob.polymarket.com/markets"
MANIFOLD_URL = "https://api.manifold.markets/v0/markets"
FETCH_INTERVAL = 600  # seconds

intents = discord.Intents.default()
client = discord.Client(intents=intents)


# ---------- Polymarket ---------- #

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


# ---------- Manifold ---------- #

async def fetch_manifold_markets(session):
    try:
        async with session.get(MANIFOLD_URL, timeout=10) as resp:
            resp.raise_for_status()
            return await resp.json()
    except Exception as e:
        print(f"[Manifold] Fetch error: {e}")
        return []


def build_manifold_lookup(markets):
    lookup = {}
    for m in markets:
        if m.get("outcomeType") != "BINARY":
            continue

        question = m.get("question", "").lower()
        prob = m.get("probability")

        if question and prob is not None:
            lookup[question] = prob

    return lookup


# ---------- Matching Logic ---------- #

def find_manifold_prob(poly_question, manifold_lookup):
    q = poly_question.lower()
    for m_q, prob in manifold_lookup.items():
        if q in m_q or m_q in q:
            return prob
    return None


# ---------- Main Loop ---------- #

async def market_loop():
    await client.wait_until_ready()

    async with aiohttp.ClientSession() as session:
        while not client.is_closed():
            poly_markets = await fetch_polymarket_markets(session)
            manifold_markets = await fetch_manifold_markets(session)

            manifold_lookup = build_manifold_lookup(manifold_markets)

            print(
                f"\n[Markets] Polymarket: {len(poly_markets)} | "
                f"Manifold: {len(manifold_lookup)}"
            )

            shown = 0

            for m in poly_markets:
                poly_prob = extract_binary_yes_prob(m)
                if poly_prob is None:
                    continue

                question = m.get("question", "")
                manifold_prob = find_manifold_prob(question, manifold_lookup)

                if manifold_prob is None:
                    continue

                print(
                    f"\n[Match] {question}\n"
                    f"  Polymarket YES ≈ {poly_prob:.2%}\n"
                    f"  Manifold   YES ≈ {manifold_prob:.2%}"
                )

                shown += 1
                if shown >= 3:
                    break

            await asyncio.sleep(FETCH_INTERVAL)


# ---------- Discord ---------- #

@client.event
async def on_ready():
    print(f"Logged in as {client.user}")
    client.loop.create_task(market_loop())


client.run(DISCORD_TOKEN)
