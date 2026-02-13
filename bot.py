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
DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL")

POLYMARKET_URL = "https://gamma-api.polymarket.com/markets?limit=500&active=true"
KALSHI_BASE_URL = "https://api.kalshi.com/trade-api/v2"
MANIFOLD_URL = "https://api.manifold.markets/v0/markets"

FETCH_INTERVAL = 120

KALSHI_API_KEY = os.environ.get("KALSHI_API_KEY")
KALSHI_API_SECRET = os.environ.get("KALSHI_API_SECRET")

intents = discord.Intents.default()
client = discord.Client(intents=intents)

# ================== UTIL ================== #

def safe_float(v):
    try:
        return float(v)
    except:
        return None

# ================== DISCORD ================== #

async def send_discord(title, market, lines, color=3447003):
    if not DISCORD_WEBHOOK_URL:
        return

    payload = {
        "embeds": [{
            "title": title,
            "description": f"**Market:** {market}\n\n" + "\n".join(lines),
            "color": color,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        }]
    }

    async with aiohttp.ClientSession() as session:
        await session.post(DISCORD_WEBHOOK_URL, json=payload)

# ================== POLYMARKET (GAMMA - FIXED) ================== #

async def fetch_polymarket(session):
    markets = []

    try:
        async with session.get(POLYMARKET_URL, timeout=20) as resp:
            print("Polymarket status:", resp.status)

            if resp.status != 200:
                return []

            data = await resp.json()

        # Gamma now returns a LIST directly
        if not isinstance(data, list):
            print("Unexpected Polymarket response type:", type(data))
            print("Sample:", str(data)[:300])
            return []

        for m in data:

            liquidity = safe_float(m.get("liquidity"))
            question = m.get("question")

            prices = m.get("outcomePrices")

            if not prices or len(prices) != 2:
                continue

            yes_price = safe_float(prices[0])

            if liquidity is None or yes_price is None:
                continue

            markets.append({
                "key": f"poly|{m.get('id')}",
                "platform": "Polymarket",
                "question": question,
                "liquidity": liquidity,
                "prob": yes_price
            })

    except Exception as e:
        print("Polymarket error:", e)

    return markets

# ================== KALSHI ================== #

async def fetch_kalshi(session):
    markets = []

    if not KALSHI_API_KEY or not KALSHI_API_SECRET:
        print("Kalshi keys not set — skipping")
        return []

    path = "/markets"
    url = f"{KALSHI_BASE_URL}{path}"

    try:
        timestamp = str(int(time.time() * 1000))
        message = f"{timestamp}GET{path}"

        secret = base64.b64decode(KALSHI_API_SECRET.strip().encode("ascii"))
        signature = hmac.new(
            secret,
            message.encode("utf-8"),
            hashlib.sha256
        ).digest()

        headers = {
            "KALSHI-ACCESS-KEY": KALSHI_API_KEY,
            "KALSHI-ACCESS-SIGNATURE": base64.b64encode(signature).decode("ascii"),
            "KALSHI-ACCESS-TIMESTAMP": timestamp
        }

        async with session.get(url, headers=headers, params={"limit": 200}, timeout=20) as resp:
            if resp.status != 200:
                print("Kalshi HTTP error:", resp.status)
                return []

            payload = await resp.json()

        for m in payload.get("markets", []):
            liquidity = safe_float(m.get("liquidity"))
            yes_bid = safe_float(m.get("yes_bid"))

            if liquidity is None or yes_bid is None:
                continue

            markets.append({
                "key": f"kalshi|{m.get('ticker')}",
                "platform": "Kalshi",
                "question": m.get("title"),
                "liquidity": liquidity,
                "prob": yes_bid / 100
            })

    except Exception as e:
        print("Kalshi error:", e)

    return markets

# ================== MANIFOLD ================== #

async def fetch_manifold(session):
    markets = []

    try:
        async with session.get(f"{MANIFOLD_URL}?limit=200", timeout=20) as resp:
            if resp.status != 200:
                print("Manifold HTTP error:", resp.status)
                return []

            payload = await resp.json()

        for m in payload:
            if m.get("isResolved"):
                continue

            liquidity = safe_float(m.get("volume24Hours"))
            prob = safe_float(m.get("probability"))

            if liquidity is None or prob is None:
                continue

            markets.append({
                "key": f"manifold|{m.get('id')}",
                "platform": "Manifold",
                "question": m.get("question"),
                "liquidity": liquidity,
                "prob": prob
            })

    except Exception as e:
        print("Manifold error:", e)

    return markets

# ================== MAIN LOOP ================== #

async def market_loop():
    await client.wait_until_ready()

    async with aiohttp.ClientSession() as session:
        while True:
            try:
                poly = await fetch_polymarket(session)
                kalshi = await fetch_kalshi(session)
                manifold = await fetch_manifold(session)

                print(
                    f"[Markets] "
                    f"Poly: {len(poly)} | "
                    f"Kalshi: {len(kalshi)} | "
                    f"Manifold: {len(manifold)}"
                )

            except Exception as e:
                print("Main loop error:", e)

            await asyncio.sleep(FETCH_INTERVAL)

# ================== DISCORD EVENTS ================== #

@client.event
async def on_ready():
    print(f"Logged in as {client.user}")
    client.loop.create_task(market_loop())

# ================== START ================== #

if not DISCORD_TOKEN:
    raise RuntimeError("DISCORD_TOKEN not set")

client.run(DISCORD_TOKEN)




