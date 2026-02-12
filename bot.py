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

POLYMARKET_URL = "https://clob.polymarket.com/markets?active=true&closed=false"
KALSHI_BASE_URL = "https://api.kalshi.com/trade-api/v2"
MANIFOLD_URL = "https://api.manifold.markets/v0/markets"

FETCH_INTERVAL = 120

ALERT_THRESHOLD = 500
WHALE_THRESHOLD = 20_000
CONFIRM_PCT = 0.05
SETUP_EXPIRY = 60 * 60
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
    except (TypeError, ValueError):
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

# ================== KALSHI AUTH ================== #

def kalshi_headers(method: str, path: str):
    timestamp = str(int(time.time() * 1000))
    message = f"{timestamp}{method.upper()}{path}"

    secret = base64.b64decode(KALSHI_API_SECRET.strip().encode("ascii"))

    signature = hmac.new(
        secret,
        message.encode("utf-8"),
        hashlib.sha256
    ).digest()

    return {
        "KALSHI-ACCESS-KEY": KALSHI_API_KEY,
        "KALSHI-ACCESS-SIGNATURE": base64.b64encode(signature).decode("ascii"),
        "KALSHI-ACCESS-TIMESTAMP": timestamp
    }

# ================== POLYMARKET ================== #

async def fetch_polymarket(session):
    markets = []

    try:
        async with session.get(POLYMARKET_URL, timeout=15) as resp:
            payload = await resp.json()

        if not isinstance(payload, list):
            print("Polymarket unexpected format")
            return []

        for m in payload:
            question = m.get("question")
            liquidity = safe_float(m.get("liquidity"))

            outcomes = m.get("outcomes", [])
            if not outcomes:
                continue

            # Many markets now store direct price
            yes_price = safe_float(outcomes[0].get("price"))

            if liquidity is not None and yes_price is not None:
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
    path = "/markets"
    url = f"{KALSHI_BASE_URL}{path}"

    try:
        headers = kalshi_headers("GET", path)

        async with session.get(url, headers=headers, params={"limit": 200}) as resp:
            if resp.status != 200:
                print("Kalshi error:", resp.status, await resp.text())
                return []

            payload = await resp.json()

        for m in payload.get("markets", []):
            liquidity = safe_float(m.get("liquidity"))
            yes_bid = safe_float(m.get("yes_bid"))

            # Kalshi prices are in cents
            if liquidity is not None and yes_bid is not None:
                markets.append({
                    "key": f"kalshi|{m.get('ticker')}",
                    "platform": "Kalshi",
                    "question": m.get("title"),
                    "liquidity": liquidity,
                    "prob": yes_bid / 100
                })

    except Exception as e:
        print("Kalshi exception:", e)

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

            volume_24h = safe_float(m.get("volume24Hours"))
            prob = safe_float(m.get("probability"))

            if volume_24h is not None and prob is not None:
                markets.append({
                    "key": f"manifold|{m.get('id')}",
                    "platform": "Manifold",
                    "question": m.get("question"),
                    "liquidity": volume_24h,
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

# ================== SETUP ================== #

async def maybe_trigger_setup(market, net_delta):
    if abs(net_delta) < ALERT_THRESHOLD:
        return
    if market["key"] in open_setups:
        return

    whale = abs(net_delta) >= WHALE_THRESHOLD
    pulled = net_delta < 0

    side = "NO" if pulled else "YES"
    entry = (1 - market["prob"]) if pulled else market["prob"]

    open_setups[market["key"]] = {
        "side": side,
        "entry": entry,
        "timestamp": time.time(),
        "confirmed": False
    }

    await send_discord(
        title=f"💧 {market['platform']} Sharp Liquidity{' 🐋' if whale else ''}",
        market=market["question"],
        lines=[
            f"{'🔴' if pulled else '🟢'} ${abs(net_delta):,.0f} {'pulled' if pulled else 'added'}",
            f"🎯 Action: Buy {side} @ {entry:.2f}"
        ],
        color=0xe74c3c if pulled else 0x2ecc71
    )

# ================== MAIN LOOP ================== #

async def market_loop():
    await client.wait_until_ready()

    async with aiohttp.ClientSession() as session:
        while True:
            poly = await fetch_polymarket(session)
            kalshi = await fetch_kalshi(session)
            manifold = await fetch_manifold(session)

            for m in poly + kalshi + manifold:
                key = m["key"]
                prev = market_cache.get(key)

                if prev:
                    delta = m["liquidity"] - prev["liquidity"]
                    track_liquidity(key, delta)
                    await maybe_trigger_setup(m, net_liquidity(key))

                market_cache[key] = {
                    "liquidity": m["liquidity"],
                    "prob": m["prob"]
                }

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



