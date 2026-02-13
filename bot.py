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

POLYMARKET_URL = "https://clob.polymarket.com/markets?limit=500"
KALSHI_BASE_URL = "https://api.kalshi.com/trade-api/v2"
MANIFOLD_URL = "https://api.manifold.markets/v0/markets"

FETCH_INTERVAL = 120

ALERT_THRESHOLD = 500
WHALE_THRESHOLD = 20_000
WINDOW_SIZE = 5

KALSHI_API_KEY = os.environ.get("KALSHI_API_KEY")
KALSHI_API_SECRET = os.environ.get("KALSHI_API_SECRET")

intents = discord.Intents.default()
client = discord.Client(intents=intents)

# ================== STATE ================== #

market_cache = {}
liquidity_windows = {}
open_setups = {}

# ================== UTIL ================== #

def safe_float(v):
    try:
        return float(v)
    except:
        return None

# ================== DISCORD ================== #

async def send_discord(title, market, lines, color):
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

# ================== POLYMARKET ================== #

async def fetch_polymarket(session):
    markets = []

    try:
        async with session.get(POLYMARKET_URL, timeout=15) as resp:
            payload = await resp.json()

        # Handle both response shapes
        if isinstance(payload, dict):
            data = payload.get("data", [])
        elif isinstance(payload, list):
            data = payload
        else:
            print("Polymarket unknown structure:", type(payload))
            return []

        for m in data:
            liquidity = safe_float(m.get("liquidity"))
            question = m.get("question")

            outcomes = m.get("outcomes", [])
            yes_prob = None

            for o in outcomes:
                if o.get("name", "").upper() == "YES":
                    bid = safe_float(o.get("bestBid"))
                    ask = safe_float(o.get("bestAsk"))
                    if bid is not None and ask is not None:
                        yes_prob = (bid + ask) / 2

            if liquidity is not None and yes_prob is not None:
                markets.append({
                    "key": f"poly|{m.get('id')}",
                    "platform": "Polymarket",
                    "question": question,
                    "liquidity": liquidity,
                    "prob": yes_prob
                })

    except Exception as e:
        print("Polymarket error:", e)

    return markets

# ================== KALSHI ================== #

async def fetch_kalshi(session):
    markets = []

    if not KALSHI_API_KEY or not KALSHI_API_SECRET:
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

        async with session.get(url, headers=headers, params={"limit": 200}) as resp:
            if resp.status != 200:
                print("Kalshi HTTP error:", resp.status)
                return []

            payload = await resp.json()

        for m in payload.get("markets", []):
            liquidity = safe_float(m.get("liquidity"))
            yes_bid = safe_float(m.get("yes_bid"))

            if liquidity is not None and yes_bid is not None:
                markets.append({
                    "key": f"kalshi|{m.get('ticker')}",
                    "platform": "Kalshi",
                    "question": m.get("title"),
                    "liquidity": liquidity,
                    "prob": yes_bid / 100
                })

    except Exception as e:
        print("Kalshi disabled (network issue):", e)
        return []

    return markets

# ================== MANIFOLD ================== #

async def fetch_manifold(session):
    markets = []

    try:
        async with session.get(f"{MANIFOLD_URL}?limit=200", timeout=15) as resp:
            payload = await resp.json()

        for m in payload:
            if m.get("isResolved"):
                continue

            liquidity = safe_float(m.get("volume24Hours"))
            prob = safe_float(m.get("probability"))

            if liquidity is not None and prob is not None:
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

# ================== LIQUIDITY ================== #

def track_liquidity(key, delta):
    window = liquidity_windows.setdefault(key, [])
    window.append(delta)
    if len(window) > WINDOW_SIZE:
        window.pop(0)

def net_liquidity(key):
    return sum(liquidity_windows.get(key, []))

# ================== MAIN LOOP ================== #

async def market_loop():
    await client.wait_until_ready()

    async with aiohttp.ClientSession() as session:
        while True:
            poly = await fetch_polymarket(session)
            kalshi = await fetch_kalshi(session)
            manifold = await fetch_manifold(session)

            print(
                f"[Markets] "
                f"Poly: {len(poly)} | "
                f"Kalshi: {len(kalshi)} | "
                f"Manifold: {len(manifold)}"
            )

            await asyncio.sleep(FETCH_INTERVAL)

# ================== DISCORD ================== #

@client.event
async def on_ready():
    print(f"Logged in as {client.user}")
    client.loop.create_task(market_loop())

client.run(DISCORD_TOKEN)




