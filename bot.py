import discord
import asyncio
import aiohttp
import os
import time
import hmac
import hashlib
import base64

# ================== CONFIG ================== #

DISCORD_TOKEN = os.environ.get("DISCORD_TOKEN")

POLYMARKET_URL = "https://clob.polymarket.com/markets"
MANIFOLD_URL = "https://api.manifold.markets/v0/markets"

FETCH_INTERVAL = 600          # 10 minutes
DISCREPANCY_THRESHOLD = 0.05  # 5%
LIQUIDITY_DELTA_THRESHOLD = 50_000  # $50k

intents = discord.Intents.default()
client = discord.Client(intents=intents)

# ================== STATE ================== #

# market_id -> {"liquidity": float, "prob": float}
polymarket_liquidity_cache = {}

# ================== POLYMARKET ================== #

async def fetch_polymarket_markets(session):
    try:
        async with session.get(POLYMARKET_URL, timeout=10) as resp:
            resp.raise_for_status()
            payload = await resp.json()
            return payload.get("data", [])
    except Exception as e:
        print(f"[Polymarket] Fetch error: {e}")
        return []


def extract_polymarket_yes_prob(market):
    outcomes = market.get("outcomes", [])
    if len(outcomes) != 2:
        return None

    for o in outcomes:
        if o.get("name", "").upper() == "YES":
            bid = o.get("bestBid")
            ask = o.get("bestAsk")
            if bid is not None and ask is not None:
                return (bid + ask) / 2

    return None

# ================== MANIFOLD ================== #

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

        q = m.get("question", "").lower()
        p = m.get("probability")

        if q and p is not None:
            lookup[q] = p

    return lookup


def find_manifold_prob(question, lookup):
    q = question.lower()
    for mq, prob in lookup.items():
        if q in mq or mq in q:
            return prob
    return None

# ================== LIQUIDITY LOGGING ================== #

def log_liquidity_delta(question, delta_liq, old_prob, new_prob):
    price_delta = None
    if old_prob is not None and new_prob is not None:
        price_delta = new_prob - old_prob

    print(
        f"\n[LIQUIDITY]\n"
        f"{question}\n"
        f"  Liquidity Δ ≈ ${delta_liq:,.0f}\n"
        f"  Price Δ     ≈ {price_delta:+.2%}" if price_delta is not None else ""
    )

# ================== MAIN LOOP ================== #

async def market_loop():
    await client.wait_until_ready()

    async with aiohttp.ClientSession() as session:
        while not client.is_closed():

            poly_markets = await fetch_polymarket_markets(session)
            manifold_markets = await fetch_manifold_markets(session)

            manifold_lookup = build_manifold_lookup(manifold_markets)

            print(
                f"\n[Markets] "
                f"Polymarket: {len(poly_markets)} | "
                f"Manifold: {len(manifold_lookup)}"
            )

            discrepancies = []

            for m in poly_markets:
                market_id = m.get("id")
                question = m.get("question", "")
                liquidity = m.get("liquidity")

                poly_prob = extract_polymarket_yes_prob(m)
                if poly_prob is None:
                    continue

                # -------- Liquidity delta tracking -------- #

                if market_id and liquidity is not None:
                    prev = polymarket_liquidity_cache.get(market_id)

                    if prev:
                        old_liq = prev["liquidity"]
                        old_prob = prev["prob"]

                        delta = liquidity - old_liq

                        if delta >= LIQUIDITY_DELTA_THRESHOLD:
                            log_liquidity_delta(
                                question=question,
                                delta_liq=delta,
                                old_prob=old_prob,
                                new_prob=poly_prob
                            )

                    polymarket_liquidity_cache[market_id] = {
                        "liquidity": liquidity,
                        "prob": poly_prob
                    }

                # -------- Consensus deviation (Poly vs Manifold) -------- #

                manifold_prob = find_manifold_prob(question, manifold_lookup)
                if manifold_prob is None:
                    continue

                spread = manifold_prob - poly_prob

                if abs(spread) >= DISCREPANCY_THRESHOLD:
                    discrepancies.append({
                        "question": question,
                        "poly": poly_prob,
                        "manifold": manifold_prob,
                        "spread": spread
                    })

            discrepancies.sort(key=lambda x: abs(x["spread"]), reverse=True)

            for d in discrepancies[:5]:
                print(
                    f"\n[DISCREPANCY]\n"
                    f"{d['question']}\n"
                    f"  Polymarket ≈ {d['poly']:.2%}\n"
                    f"  Manifold   ≈ {d['manifold']:.2%}\n"
                    f"  Spread     ≈ {d['spread']:+.2%}"
                )

            await asyncio.sleep(FETCH_INTERVAL)

# ================== DISCORD ================== #

@client.event
async def on_ready():
    print(f"Logged in as {client.user}")
    client.loop.create_task(market_loop())


client.run(DISCORD_TOKEN)
