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
KALSHI_BASE_URL = "https://trading-api.kalshi.com"

KALSHI_API_KEY = os.environ.get("KALSHI_API_KEY")
KALSHI_API_SECRET = os.environ.get("KALSHI_API_SECRET")

FETCH_INTERVAL = 600          # 10 minutes
DISCREPANCY_THRESHOLD = 0.05  # 5%

intents = discord.Intents.default()
client = discord.Client(intents=intents)

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

# ================== KALSHI ================== #

def kalshi_headers(method, path):
    timestamp = str(int(time.time() * 1000))
    message = f"{timestamp}{method.upper()}{path}"

    signature = hmac.new(
        KALSHI_API_SECRET.encode(),
        message.encode(),
        hashlib.sha256
    ).digest()

    return {
        "KALSHI-ACCESS-KEY": KALSHI_API_KEY,
        "KALSHI-ACCESS-SIGNATURE": base64.b64encode(signature).decode(),
        "KALSHI-ACCESS-TIMESTAMP": timestamp,
        "Content-Type": "application/json"
    }


async def fetch_kalshi_markets(session, limit=50):
    path = f"/trade-api/v2/markets?limit={limit}"
    url = KALSHI_BASE_URL + path

    try:
        async with session.get(
            url,
            headers=kalshi_headers("GET", path),
            timeout=10
        ) as resp:
            resp.raise_for_status()
            payload = await resp.json()
            return payload.get("markets", [])
    except Exception as e:
        print(f"[Kalshi] Market fetch error: {e}")
        return []


async def fetch_kalshi_yes_prob(session, ticker):
    path = f"/trade-api/v2/markets/{ticker}/orderbook"
    url = KALSHI_BASE_URL + path

    try:
        async with session.get(
            url,
            headers=kalshi_headers("GET", path),
            timeout=10
        ) as resp:
            resp.raise_for_status()
            payload = await resp.json()

            yes = payload.get("orderbook", {}).get("YES", {})
            bids = yes.get("bids", [])
            asks = yes.get("asks", [])

            if not bids or not asks:
                return None

            return (bids[0]["price"] + asks[0]["price"]) / 200

    except Exception as e:
        print(f"[Kalshi] Orderbook error ({ticker}): {e}")
        return None

# ================== MAIN LOOP ================== #

async def market_loop():
    await client.wait_until_ready()

    async with aiohttp.ClientSession() as session:
        while not client.is_closed():

            poly_markets = await fetch_polymarket_markets(session)
            manifold_markets = await fetch_manifold_markets(session)
            kalshi_markets = await fetch_kalshi_markets(session)

            manifold_lookup = build_manifold_lookup(manifold_markets)

            print(
                f"\n[Markets] "
                f"Polymarket: {len(poly_markets)} | "
                f"Manifold: {len(manifold_lookup)} | "
                f"Kalshi: {len(kalshi_markets)}"
            )

            # ---- Polymarket vs Manifold Discrepancies ---- #

            discrepancies = []

            for m in poly_markets:
                poly_prob = extract_polymarket_yes_prob(m)
                if poly_prob is None:
                    continue

                question = m.get("question", "")
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

            # ---- Kalshi Sample Prices ---- #

            shown = 0
            for km in kalshi_markets:
                ticker = km.get("ticker")
                title = km.get("title")

                if not ticker:
                    continue

                prob = await fetch_kalshi_yes_prob(session, ticker)
                if prob is None:
                    continue

                print(f"[Kalshi] {title} | YES ≈ {prob:.2%}")

                shown += 1
                if shown >= 3:
                    break

            await asyncio.sleep(FETCH_INTERVAL)

# ================== DISCORD ================== #

@client.event
async def on_ready():
    print(f"Logged in as {client.user}")
    client.loop.create_task(market_loop())


client.run(DISCORD_TOKEN)

