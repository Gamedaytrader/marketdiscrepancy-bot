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

POLYMARKET_URL = "https://clob.polymarket.com/markets"
KALSHI_BASE_URL = BASE_URL = "https://api.elections.kalshi.com/trade-api/v2"

FETCH_INTERVAL = 120  # 2 minutes

ALERT_THRESHOLD = 3_000
WHALE_THRESHOLD = 20_000
CONFIRM_PCT = 0.05
SETUP_EXPIRY = 60 * 60
WINDOW_SIZE = 5

KALSHI_API_KEY = os.environ.get("KALSHI_API_KEY")
KALSHI_API_SECRET = os.environ.get("KALSHI_API_SECRET")  # base64

intents = discord.Intents.default()
client = discord.Client(intents=intents)

# ================== STATE ================== #

market_cache = {}            # key -> {liquidity, prob}
liquidity_windows = {}       # key -> [deltas]
open_setups = {}             # key -> setup object

# ================== DISCORD WEBHOOK ================== #

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
        async with session.post(DISCORD_WEBHOOK_URL, json=payload):
            pass

# ================== KALSHI AUTH ================== #

def kalshi_headers(method: str, path: str):
    if not KALSHI_API_SECRET:
        raise RuntimeError("KALSHI_API_SECRET not set")

    timestamp = str(int(time.time() * 1000))
    message = f"{timestamp}{method.upper()}{path}"

    # IMPORTANT: strip whitespace + encode
    private_key_clean = KALSHI_API_SECRET.strip()

    secret = base64.b64decode(private_key_clean.encode("ascii"))

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
    async with session.get(POLYMARKET_URL, timeout=15) as resp:
        payload = await resp.json()
        for m in payload.get("data", []):
            market_id = f"poly|{m.get('id')}"
            question = m.get("question")
            liquidity = m.get("liquidity")

            yes_prob = None
            for o in m.get("outcomes", []):
                if o.get("name", "").upper() == "YES":
                    bid, ask = o.get("bestBid"), o.get("bestAsk")
                    if bid and ask:
                        yes_prob = (bid + ask) / 2

            if yes_prob is not None and liquidity is not None:
                markets.append({
                    "key": market_id,
                    "question": question,
                    "liquidity": float(liquidity),
                    "prob": float(yes_prob)
                })
    return markets

# ================== KALSHI ================== #

async def fetch_kalshi(session):
    markets = []
    path = "/trade-api/v2/markets"
    url = f"{KALSHI_BASE_URL}{path}"

    headers = kalshi_headers("GET", path)
    params = {"limit": 200}

    async with session.get(url, headers=headers, params=params) as resp:
        payload = await resp.json()

        for m in payload.get("markets", []):
            market_id = f"kalshi|{m.get('id')}"
            question = m.get("title")

            yes_price = m.get("yes_price")
            volume = m.get("volume")

            if yes_price is None or volume is None:
                continue

            markets.append({
                "key": market_id,
                "question": question,
                "liquidity": float(volume),  # proxy
                "prob": float(yes_price)
            })

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

async def maybe_trigger_setup(key, question, net_delta, yes_price):
    if abs(net_delta) < ALERT_THRESHOLD:
        return
    if key in open_setups:
        return

    whale = abs(net_delta) >= WHALE_THRESHOLD
    pulled = net_delta < 0

    side = "NO" if pulled else "YES"
    entry = (1 - yes_price) if pulled else yes_price

    open_setups[key] = {
        "side": side,
        "entry": entry,
        "timestamp": time.time(),
        "confirmed": False
    }

    await send_discord(
        title=f"💧 Sharp Liquidity Move{' 🐋' if whale else ''}",
        market=question,
        lines=[
            f"{'🔴' if pulled else '🟢'} ${abs(net_delta):,.0f} {'pulled' if pulled else 'added'}",
            "📌 Liquidity moved first",
            "",
            f"🎯 Action: Buy {side} @ {entry:.2f}"
        ],
        color=0xe74c3c if pulled else 0x2ecc71
    )

# ================== FOLLOW UPS ================== #

async def check_followups(key, question, yes_price):
    setup = open_setups.get(key)
    if not setup:
        return

    now = time.time()

    if now - setup["timestamp"] > SETUP_EXPIRY:
        del open_setups[key]
        return

    current = yes_price if setup["side"] == "YES" else (1 - yes_price)
    move_pct = (current - setup["entry"]) / setup["entry"]

    if not setup["confirmed"] and move_pct >= CONFIRM_PCT:
        setup["confirmed"] = True
        await send_discord(
            title="✅ CONFIRMED: Price Reacting",
            market=question,
            lines=[
                f"{setup['side']}: {setup['entry']:.2f} → {current:.2f}",
                f"📈 {move_pct*100:.1f}%",
                "",
                "🧠 Liquidity led. Market followed."
            ],
            color=0xf1c40f
        )

# ================== MAIN LOOP ================== #

async def market_loop():
    await client.wait_until_ready()

    async with aiohttp.ClientSession() as session:
        while True:
            poly = await fetch_polymarket(session)
            kalshi = await fetch_kalshi(session)

            for m in poly + kalshi:
                key = m["key"]
                question = m["question"]
                liquidity = m["liquidity"]
                prob = m["prob"]

                prev = market_cache.get(key)
                if prev:
                    delta = liquidity - prev["liquidity"]
                    track_liquidity(key, delta)

                    await maybe_trigger_setup(
                        key,
                        question,
                        net_liquidity(key),
                        prob
                    )

                    await check_followups(key, question, prob)

                market_cache[key] = {
                    "liquidity": liquidity,
                    "prob": prob
                }

            await asyncio.sleep(FETCH_INTERVAL)

# ================== DISCORD ================== #

@client.event
async def on_ready():
    print(f"Logged in as {client.user}")
    client.loop.create_task(market_loop())

client.run(DISCORD_TOKEN)

