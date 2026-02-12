import discord
import asyncio
import aiohttp
import os
import time

# ================== CONFIG ================== #

DISCORD_TOKEN = os.environ.get("DISCORD_TOKEN")
DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL")

POLYMARKET_URL = "https://clob.polymarket.com/markets"

FETCH_INTERVAL = 120  # 2 minutes

ALERT_THRESHOLD = 3_000
WHALE_THRESHOLD = 20_000
CONFIRM_PCT = 0.05           # 5% price move
SETUP_EXPIRY = 60 * 60       # 1 hour
WINDOW_SIZE = 5              # rolling liquidity window

intents = discord.Intents.default()
client = discord.Client(intents=intents)

# ================== STATE ================== #

polymarket_cache = {}        # market_id -> {liquidity, prob}
liquidity_windows = {}       # market_id -> [deltas]
open_setups = {}             # market_id -> setup object

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

# ================== POLYMARKET ================== #

async def fetch_polymarket_markets(session):
    try:
        async with session.get(POLYMARKET_URL, timeout=15) as resp:
            resp.raise_for_status()
            payload = await resp.json()
            return payload.get("data", [])
    except Exception as e:
        print(f"[Polymarket] Fetch error: {e}")
        return []

def extract_yes_prob(market):
    for o in market.get("outcomes", []):
        if o.get("name", "").upper() == "YES":
            bid = o.get("bestBid")
            ask = o.get("bestAsk")
            if bid is not None and ask is not None:
                return (bid + ask) / 2
    return None

# ================== LIQUIDITY UTILS ================== #

def track_liquidity(market_id, delta):
    window = liquidity_windows.setdefault(market_id, [])
    window.append(delta)
    if len(window) > WINDOW_SIZE:
        window.pop(0)

def net_liquidity(market_id):
    return sum(liquidity_windows.get(market_id, []))

# ================== SETUP ================== #

async def maybe_trigger_setup(market_id, question, net_delta, yes_price):
    if abs(net_delta) < ALERT_THRESHOLD:
        return
    if market_id in open_setups:
        return

    whale = abs(net_delta) >= WHALE_THRESHOLD
    pulled = net_delta < 0

    action_side = "NO" if pulled else "YES"
    action_price = (1 - yes_price) if pulled else yes_price

    open_setups[market_id] = {
        "side": action_side,
        "entry": action_price,
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
            f"🎯 Action: Buy {action_side} @ {action_price:.2f}"
        ],
        color=0xe74c3c if pulled else 0x2ecc71
    )

# ================== FOLLOW UPS ================== #

async def check_followups(market_id, question, yes_price):
    setup = open_setups.get(market_id)
    if not setup:
        return

    now = time.time()

    # TIMEOUT
    if now - setup["timestamp"] > SETUP_EXPIRY:
        await send_discord(
            title="❌ INVALIDATED",
            market=question,
            lines=["Timed out with no price reaction"],
            color=0x95a5a6
        )
        del open_setups[market_id]
        return

    current_price = yes_price if setup["side"] == "YES" else (1 - yes_price)
    move_pct = (current_price - setup["entry"]) / setup["entry"]

    # CONFIRMED
    if not setup["confirmed"] and move_pct >= CONFIRM_PCT:
        setup["confirmed"] = True
        await send_discord(
            title="✅ CONFIRMED: Price Reacting",
            market=question,
            lines=[
                f"{setup['side']}: {setup['entry']:.2f} → {current_price:.2f}",
                f"📈 {move_pct*100:.1f}%",
                "",
                "🧠 Liquidity led. Market followed."
            ],
            color=0xf1c40f
        )

    # LIQUIDITY REVERSAL
    if abs(net_liquidity(market_id)) < ALERT_THRESHOLD:
        await send_discord(
            title="❌ INVALIDATED",
            market=question,
            lines=["Liquidity reversed before confirmation"],
            color=0x95a5a6
        )
        del open_setups[market_id]

# ================== MAIN LOOP ================== #

async def market_loop():
    await client.wait_until_ready()

    async with aiohttp.ClientSession() as session:
        while not client.is_closed():
            markets = await fetch_polymarket_markets(session)

            for m in markets:
                market_id = m.get("id")
                question = m.get("question", "")
                liquidity = m.get("liquidity")

                yes_prob = extract_yes_prob(m)
                if market_id is None or liquidity is None or yes_prob is None:
                    continue

                prev = polymarket_cache.get(market_id)

                if prev:
                    delta = liquidity - prev["liquidity"]
                    track_liquidity(market_id, delta)

                    net_delta = net_liquidity(market_id)

                    await maybe_trigger_setup(
                        market_id,
                        question,
                        net_delta,
                        yes_prob
                    )

                    await check_followups(
                        market_id,
                        question,
                        yes_prob
                    )

                polymarket_cache[market_id] = {
                    "liquidity": liquidity,
                    "prob": yes_prob
                }

            await asyncio.sleep(FETCH_INTERVAL)
        @client.event
async def on_ready():
    print(f"Logged in as {client.user}")

    await send_discord(
        title="🧪 TEST ALERT",
        market="System Check",
        lines=["If you see this, webhooks are working"],
        color=0x3498db
    )

    client.loop.create_task(market_loop())


# ================== DISCORD ================== #

@client.event
async def on_ready():
    print(f"Logged in as {client.user}")
    client.loop.create_task(market_loop())

client.run(DISCORD_TOKEN)
