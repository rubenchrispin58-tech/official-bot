import asyncio
import json
import logging
import math
import os
import time
from collections import deque
from dataclasses import dataclass, asdict
from pathlib import Path

from aiohttp import ClientSession, ClientTimeout, web
from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    WebAppInfo,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
log = logging.getLogger("b2k_engine")

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
WEBAPP_URL = os.getenv("WEBAPP_URL", "").strip()
PORT = int(os.getenv("PORT", "10000"))

PAIRS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT"]
TIMEFRAMES = {"S5": 5, "S15": 15, "S30": 30, "M1": 60}

PROMO_CODE = "FRIENDXYZLOERADB"
PARTNER_LINK = "https://pocket-friends.co/r/xyzloeradb"


# ───────────────────────────── Indicateurs Réels ─────────────────────────────
def sma(values: list[float], period: int) -> float | None:
    if len(values) < period:
        return None
    return sum(values[-period:]) / period


def ema_series(values: list[float], period: int) -> list[float]:
    if not values:
        return []
    k = 2.0 / (period + 1.0)
    out = [values[0]]
    for v in values[1:]:
        out.append(v * k + out[-1] * (1.0 - k))
    return out


def rsi(values: list[float], period: int = 14) -> float | None:
    if len(values) < period + 1:
        return None
    gains = 0.0
    losses = 0.0
    for i in range(1, period + 1):
        diff = values[i] - values[i - 1]
        gains += max(diff, 0.0)
        losses += max(-diff, 0.0)
    avg_gain = gains / period
    avg_loss = losses / period
    for i in range(period + 1, len(values)):
        diff = values[i] - values[i - 1]
        avg_gain = (avg_gain * (period - 1) + max(diff, 0.0)) / period
        avg_loss = (avg_loss * (period - 1) + max(-diff, 0.0)) / period
    if avg_loss == 0.0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def macd(values: list[float], fast: int = 12, slow: int = 26, signal: int = 9):
    if len(values) < slow + signal:
        return None
    macd_line = [a - b for a, b in zip(ema_series(values, fast), ema_series(values, slow))]
    sig_line = ema_series(macd_line, signal)
    hist = macd_line[-1] - sig_line[-1]
    return macd_line[-1], sig_line[-1], hist


def bollinger(values: list[float], period: int = 20, mult: float = 2.0):
    if len(values) < period:
        return None
    window = values[-period:]
    mid = sum(window) / period
    var = sum((v - mid) ** 2 for v in window) / period
    sd = math.sqrt(var)
    return mid - mult * sd, mid, mid + mult * sd, sd


def clamp(val: float, lo: float = -1.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, val))


# ───────────────────────────── Bougies & Analyse ─────────────────────────────
class CandleBuilder:
    def __init__(self, tf_sec: int, maxlen: int = 250):
        self.tf_sec = tf_sec
        self.closes: deque[float] = deque(maxlen=maxlen)
        self._bucket: int | None = None
        self._last: float | None = None

    def push(self, ts: float, price: float):
        bucket = int(ts) // self.tf_sec
        if self._bucket is None:
            self._bucket = bucket
        elif bucket != self._bucket and self._last is not None:
            self.closes.append(self._last)
            self._bucket = bucket
        self._last = price

    def series(self) -> list[float]:
        if self._last is None:
            return list(self.closes)
        return list(self.closes) + [self._last]


@dataclass
class AnalysisResult:
    pair: str
    tf: str
    ready: bool
    samples: int
    score: float
    bias: str
    uncertainty: str
    indicators: dict


def analyze_closes(pair: str, tf: str, closes: list[float]) -> AnalysisResult:
    n = len(closes)
    if n < 15:
        return AnalysisResult(
            pair=pair,
            tf=tf,
            ready=False,
            samples=n,
            score=0.0,
            bias="DONNÉES INSUFFISANTES",
            uncertainty="Élevée : pas assez de clôtures collectées pour calculer les indicateurs.",
            indicators={},
        )

    last_px = closes[-1]
    diffs = [closes[i] - closes[i - 1] for i in range(max(1, n - 15), n)]
    vol = math.sqrt(sum(d * d for d in diffs) / len(diffs)) or 1e-9

    r_val = rsi(closes)
    m_val = macd(closes)
    b_val = bollinger(closes)
    sma_fast = sma(closes, 5)
    sma_slow = sma(closes, 13)

    components: list[float] = []
    if r_val is not None:
        components.append(clamp((50.0 - r_val) / 25.0))
    if m_val is not None:
        components.append(clamp(math.tanh(m_val[2] / vol)))
    if b_val is not None and b_val[3] > 0:
        components.append(clamp(-((last_px - b_val[1]) / b_val[3]) / 2.0))
    if sma_fast is not None and sma_slow is not None:
        components.append(clamp(math.tanh((sma_fast - sma_slow) / vol)))
    if not components:
        components.append(clamp(math.tanh(sum(diffs[-3:]) / vol)))

    score = sum(components) / len(components)
    if score >= 0.15:
        bias = "PRESSION HAUSSIÈRE (TECHNIQUE)"
    elif score <= -0.15:
        bias = "PRESSION BAISSIÈRE (TECHNIQUE)"
    else:
        bias = "NEUTRE / CONSOLIDATION"

    uncertainty = (
        f"Incertitude active : {n} points de série ({tf}). "
        "Un score technique n'est pas une certitude de marché ; le bruit court terme reste élevé."
    )

    indicators = {
        "rsi_14": round(r_val, 2) if r_val is not None else None,
        "macd_hist": round(m_val[2], 6) if m_val is not None else None,
        "boll_mid": round(b_val[1], 4) if b_val is not None else None,
        "sma_5": round(sma_fast, 4) if sma_fast is not None else None,
        "sma_13": round(sma_slow, 4) if sma_slow is not None else None,
    }

    return AnalysisResult(
        pair=pair,
        tf=tf,
        ready=True,
        samples=n,
        score=round(score, 3),
        bias=bias,
        uncertainty=uncertainty,
        indicators=indicators,
    )


# ───────────────────────────── Flux de Prix Binance ─────────────────────────────
class BinanceFeed:
    URL = "https://api.binance.com/api/v3/ticker/price"

    def __init__(self, symbols: list[str]):
        self.symbols = set(symbols)
        self.session: ClientSession | None = None

    async def fetch(self) -> dict[str, float]:
        if self.session is None or self.session.closed:
            self.session = ClientSession(timeout=ClientTimeout(total=3))
        async with self.session.get(self.URL) as resp:
            resp.raise_for_status()
            data = await resp.json()
        if not isinstance(data, list):
            return {}
        out: dict[str, float] = {}
        for row in data:
            sym = row.get("symbol")
            px = row.get("price")
            if sym in self.symbols and px is not None:
                out[sym] = float(px)
        return out

    async def close(self):
        if self.session and not self.session.closed:
            await self.session.close()


class MarketEngine:
    def __init__(self):
        self.feed = BinanceFeed(PAIRS)
        self.candles = {
            pair: {tf: CandleBuilder(sec) for tf, sec in TIMEFRAMES.items()}
            for pair in PAIRS
        }
        self.prices: dict[str, float] = {}
        self.analyses: dict[str, dict[str, AnalysisResult]] = {
            pair: {
                tf: analyze_closes(pair, tf, [])
                for tf in TIMEFRAMES
            }
            for pair in PAIRS
        }
        self.last_update: float = 0.0

    async def run(self):
        next_tick = time.monotonic()
        while True:
            try:
                prices = await self.feed.fetch()
                if prices:
                    now = time.time()
                    self.prices.update(prices)
                    self.last_update = now
                    for pair, px in prices.items():
                        for tf, cb in self.candles[pair].items():
                            cb.push(now, px)
                            self.analyses[pair][tf] = analyze_closes(pair, tf, cb.series())
            except Exception as exc:
                log.warning("Erreur flux prix : %s", exc)

            next_tick += 1.0
            await asyncio.sleep(max(0.0, next_tick - time.monotonic()))


engine = MarketEngine()


# ───────────────────────────── Serveur Web & API ─────────────────────────────
async def index(request: web.Request):
    html_path = Path(__file__).parent / "webapp" / "index.html"
    if html_path.exists():
        return web.FileResponse(html_path)
    return web.Response(text="Serveur actif", content_type="text/plain")


async def api_state(request: web.Request):
    pair = request.query.get("pair", "BTCUSDT").upper()
    if pair not in engine.analyses:
        pair = "BTCUSDT"
    return web.json_response({
        "ts": engine.last_update,
        "pair": pair,
        "pairs": PAIRS,
        "price": engine.prices.get(pair),
        "analyses": {tf: asdict(res) for tf, res in engine.analyses[pair].items()},
        "promo_code": PROMO_CODE,
        "partner_link": PARTNER_LINK,
    })


# ───────────────────────────── Bot Telegram ─────────────────────────────
def build_main_keyboard() -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = [
        [
            InlineKeyboardButton(text="📊 Analyser BTCUSDT (S30)", callback_data="analyze:BTCUSDT:S30"),
            InlineKeyboardButton(text="⏱️ Analyser BTCUSDT (M1)", callback_data="analyze:BTCUSDT:M1"),
        ],
        [
            InlineKeyboardButton(text="⚡ S5 / S15 Rapide", callback_data="analyze:BTCUSDT:S5"),
            InlineKeyboardButton(text="🎁 Code Promo & Lien", callback_data="promo_info"),
        ],
    ]
    if WEBAPP_URL.startswith("https://"):
        rows.append([InlineKeyboardButton(text="🚀 Ouvrir la Mini-App", web_app=WebAppInfo(url=WEBAPP_URL))])
    else:
        rows.append([InlineKeyboardButton(text="🔗 Lien Partenaire", url=PARTNER_LINK)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def format_analysis_message(pair: str, tf: str) -> str:
    px = engine.prices.get(pair)
    res = engine.analyses.get(pair, {}).get(tf)
    px_str = f"{px:.4f}" if px is not None else "en attente"
    if not res or not res.ready:
        samples = res.samples if res else 0
        return (
            f"📈 *Analyse Technique — {pair} ({tf})*\n"
            f"Prix actuel : *{px_str}*\n"
            f"Collecte en cours : *{samples}/15* points minimum requis.\n\n"
            f"⚠️ *Incertitude :* Pas assez de données réelles pour un diagnostic fiable."
        )

    ind = res.indicators
    return (
        f"📈 *Analyse Technique — {pair} ({tf})*\n"
        f"Prix actuel : *{px_str}*\n"
        f"Lecture : *{res.bias}*\n"
        f"Score technique : *{res.score}*\n"
        f"Indicateurs : RSI(14)={ind.get('rsi_14')} | MACD Hist={ind.get('macd_hist')} | SMA5={ind.get('sma_5')}\n\n"
        f"⚠️ *Incertitude :* {res.uncertainty}\n"
        f"🎁 Code promo : `{PROMO_CODE}`"
    )


async def run_bot():
    if not BOT_TOKEN:
        log.error("BOT_TOKEN manquant dans Environment.")
        return

    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher()

    @dp.message(CommandStart())
    async def on_start(message: Message):
        name = message.from_user.first_name if message.from_user else "frère"
        await message.answer(
            f"Salut {name} ! Moteur d'analyse réel actif
