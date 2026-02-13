import discord
import asyncio
import aiohttp
import os
import time
import hmac
import hashlib
import base64
import logging
import sys
import websockets
import json

# ================== LOGGING CONFIG ================== #

logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(message)s',
    datefmt='%H:%M:%S',
    stream=sys.stdout
)
logger = logging.getLogger(__name__)

# ================== CONFIG ================== #

DISCORD_TOKEN = os.environ.get("DISCORD_TOKEN")
DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL")

POLYMARKET_URL = "https://gamma-api.polymarket.com/markets?limit=500&active=true"
POLYMARKET_WS_URL = "wss://ws-mainnet-1.polymarket.com/ws"
KALSHI_BASE_URL = "https://api.kalshi.com/trade-api/v2"
MANIFOLD_URL = "https://api.manifold.markets/v0/markets"

FETCH_INTERVAL = 30  # Fetch every 30 seconds for more live data

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

# ================== POLYMARKET ================== #

async def fetch_polymarket(session):
    markets = []

    try:
        async with session.get(POLYMARKET_URL, timeout=20) as resp:
            logger.info(f"Polymarket status: {resp.status}")

            if resp.status != 200:
                return []

            payload = await resp.json()

        logger.info(f"Polymarket payload type: {type(payload)}")

        # Defensive parsing
        if isinstance(payload, list):
            data = payload
        elif isinstance(payload, dict):
            if "data" in payload:
                data = payload["data"]
            elif "markets" in payload:
                data = payload["markets"]
            else:
                logger.info(f"Polymarket unknown keys: {list(payload.keys())}")
                return []
        else:
            logger.info("Unknown Polymarket format")
            return []

        logger.info(f"Polymarket raw count: {len(data)}")
        
        # DEBUG: log first item to see actual structure
        if len(data) > 0:
            logger.info(f"Polymarket first item keys: {list(data[0].keys())}")
            logger.info(f"Polymarket first item: {data[0]}")

        for m in data:
            liquidity = safe_float(
                m.get("liquidity")
                or m.get("liquidityNum")
            )

            prices = (
                m.get("outcomePrices")
                or m.get("outcome_prices")
            )

            question = m.get("question")
            
            # DEBUG: log why items are being skipped
            if not prices:
                logger.debug(f"Skipping market: no prices field")
                continue
            
            if len(prices) != 2:
                logger.debug(f"Skipping market: prices length {len(prices)} != 2, prices: {prices}")
                continue

            yes_price = safe_float(prices[0])

            if liquidity is None:
                logger.debug(f"Skipping market: liquidity is None")
                continue
                
            if yes_price is None:
                logger.debug(f"Skipping market: yes_price is None, prices[0]: {prices[0]}")
                continue

            markets.append({
                "key": f"poly|{m.get('id')}",
                "platform": "Polymarket",
                "question": question,
                "liquidity": liquidity,
                "prob": yes_price
            })

    except Exception as e:
        logger.error(f"Polymarket error: {e}", exc_info=True)

    return markets

# ================== POLYMARKET WEBSOCKET ================== #

async def polymarket_websocket():
    """Connect to Polymarket WebSocket for real-time updates"""
    
    try:
        async with websockets.connect(POLYMARKET_WS_URL, timeout=20) as websocket:
            logger.info("Connected to Polymarket WebSocket")
            
            while not client.is_closed():
                try:
                    message = await websocket.recv()
                    data = json.loads(message)
                    logger.info(f"Polymarket live update: {data}")
                except asyncio.TimeoutError:
                    logger.warning("WebSocket timeout, reconnecting...")
                    break
                except Exception as e:
                    logger.error(f"WebSocket error: {e}")
                    break
    except Exception as e:
        logger.error(f"Polymarket WebSocket connection error: {e}")
    
    # Reconnect after delay
    await asyncio.sleep(5)

# ================== KALSHI ================== #

async def fetch_kalshi(session):
    markets = []

    if not KALSHI_API_KEY or not KALSHI_API_SECRET:
        logger.info("Kalshi keys not set — skipping")
        return []

    path = "/markets"
    url = f"{KALSHI_BASE_URL}{path}"

    try:
        timestamp = str(int(time.time() * 1000))
        message = f"{timestamp}GET{path}"

        secret = base64.b64decode(KALSHI_API_SECRET.strip())
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
            logger.info(f"Kalshi status: {resp.status}")

            if resp.status != 200:
                return []

            payload = await resp.json()

        raw = payload.get("markets", [])
        logger.info(f"Kalshi raw count: {len(raw)}")

        for m in raw:
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
        logger.error(f"Kalshi error: {e}")

    return markets

# ================== MANIFOLD ================== #

async def fetch_manifold(session):
    markets = []

    try:
        async with session.get(f"{MANIFOLD_URL}?limit=200", timeout=20) as resp:
            logger.info(f"Manifold status: {resp.status}")

            if resp.status != 200:
                return []

            payload = await resp.json()

        logger.info(f"Manifold raw count: {len(payload)}")

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
        logger.error(f"Manifold error: {e}")

    return markets

# ================== MAIN LOOP ================== #

async def market_loop():
    await client.wait_until_ready()
    logger.info("Market loop started")

    async with aiohttp.ClientSession() as session:
        while not client.is_closed():
            try:
                poly = await fetch_polymarket(session)
                kalshi = await fetch_kalshi(session)
                manifold = await fetch_manifold(session)

                logger.info(
                    f"Poly: {len(poly)} | "
                    f"Kalshi: {len(kalshi)} | "
                    f"Manifold: {len(manifold)}"
                )

                # Debug if something is zero
                if len(poly) == 0:
                    logger.warning("Polymarket returned 0 parsed markets")
                if len(kalshi) == 0 and KALSHI_API_KEY:
                    logger.warning("Kalshi returned 0 parsed markets")
                if len(manifold) == 0:
                    logger.warning("Manifold returned 0 parsed markets")

            except Exception as e:
                logger.error(f"Main loop error: {e}")

            await asyncio.sleep(FETCH_INTERVAL)

# ================== DISCORD EVENTS ================== #

@client.event
async def on_ready():
    logger.info(f"Logged in as {client.user}")
    client.loop.create_task(market_loop())
    client.loop.create_task(polymarket_websocket())

# ================== START ================== #

if not DISCORD_TOKEN:
    raise RuntimeError("DISCORD_TOKEN not set")

client.run(DISCORD_TOKEN)
