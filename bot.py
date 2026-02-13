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

        for m in data:
            # Skip closed/inactive markets
            if m.get("closed") or not m.get("active"):
