import asyncio
import datetime
import io
import logging
import math
import os
import random
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path

from aiohttp import ClientSession, ClientTimeout, web
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    BufferedInputFile,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    LinkPreviewOptions,
    Message,
    WebAppInfo,
)
from PIL import Image, ImageDraw

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
log = logging.getLogger("b2k_signal_bot")

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
WEBAPP_URL = os.getenv("WEBAPP_URL", "").strip()
PORT = int(os.getenv("PORT", "10000"))

ADMIN_USERNAME = "b2k_ruben"
ADMIN_URL = f"https://t.me/{ADMIN_USERNAME}"
PROMO_CODE = "FRIENDXYZLOERADB"
PARTNER_LINK = "https://pocket-friends.co/r/xyzloeradb"

FREE_TRIALS_LIMIT = 5
ACTIVATION_CODE = os.getenv("ACTIVATION_CODE", "B2K20").strip()

ASSETS_DIR = Path(__file__).parent / "assets"
ASSETS_DIR.mkdir(parents=True, exist_ok=True)

OTC_PAIRS = [
    "EUR/USD (OTC)",
    "AUD/USD (OTC)",
    "GBP/USD (OTC)",
    "USD/JPY (OTC)",
    "EUR/CAD (OTC)",
    "CAD/JPY (OTC)",
]
CRYPTO_PAIRS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT"]
ALL_PAIRS = OTC_PAIRS + CRYPTO_PAIRS
TIMEFRAMES = {"S5": 5, "S15": 15, "S30": 30, "M1": 60}


# ───────────────────────────── Visuels Rectangulaires ─────────────────────────────
def make_rectangle_banner(kind: str) -> bytes:
    w, h = 900, 320
    if kind == "BUY":
        bg = (14, 46, 34)
        accent = (34, 197, 94)
        label = "BUY"
    elif kind == "SELL":
        bg = (52, 18, 24)
        accent = (239, 68, 68)
        label = "SELL"
    else:
        bg = (20, 24, 38)
        accent = (59, 130, 246)
        label = "B2K"

    img = Image.new("RGB", (w, h), bg)
    draw = ImageDraw.Draw(img)
    draw.rectangle([16, 16, w - 16, h - 16], outline=accent, width=6)
    draw.rectangle([48, 72, w - 48, h - 72], fill=(28, 32, 46), outline=accent, width=3)

    # Barre de niveau rectangulaire stylisée
    bar_x0, bar_y0, bar_x1, bar_y1 = 110, 135, w - 110, 185
    draw.rectangle([bar_x0, bar_y0, bar_x1, bar_y1], fill=(45, 50, 68))
    fill_w = int((bar_x1 - bar_x0) * (0.76 if kind == "BUY" else 0.72 if kind == "SELL" else 0.55))
    draw.rectangle([bar_x0, bar_y0, bar_x0 + fill_w, bar_y1], fill=accent)

    # Indicateur directionnel géométrique net
    cx, cy = w // 2, 225
    if kind == "BUY":
        draw.polygon([(cx, cy - 22), (cx - 28, cy + 16), (cx + 28, cy + 16)], fill=accent)
    elif kind == "SELL":
        draw.polygon([(cx, cy + 22), (cx - 28, cy - 16), (cx + 28, cy - 16)], fill=accent)
    else:
        draw.rectangle([cx - 45, cy - 8, cx + 45, cy + 8], fill=accent)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


async def get_photo_input(bot: Bot, slot: str):
    custom_file = ASSETS_DIR / f"{slot}.jpg"
    custom_png = ASSETS_DIR / f"{slot}.png"
    target = custom_file if custom_file.exists() else (custom_png if custom_png.exists() else None)
    if target is not None:
        return BufferedInputFile(target.read_bytes(), filename=target.name)

    tg_file_id = media_store.file_ids.get(slot)
    if tg_file_id:
        buf = io.BytesIO()
        await bot.download(tg_file_id, destination=buf)
        return BufferedInputFile(buf.getvalue(), filename=f"{slot}.jpg")

    kind = "BUY" if slot == "buy" else ("SELL" if slot == "sell" else "MENU")
    return BufferedInputFile(make_rectangle_banner(kind), filename=f"{slot}.png")


class MediaStore:
    def __init__(self):
        self.file_ids: dict[str, str] = {}
        self.awaiting_slot: dict[int, str] = {}


media_store = MediaStore()


# ───────────────────────────── Textes FR / EN ─────────────────────────────
TEXTS = {
    "fr": {
        "choose_lang": "Choisis une langue / Choose a language :",
        "lang_set": "Langue : Francais",
        "home_body": (
            "B2K Signal Engine\n"
            "Choisis une action ci-dessous.\n"
            "Rappel : tout signal comporte une part d'incertitude."
        ),
        "btn_signal": "Get signal",
        "btn_account": "Mon compte",
        "btn_activate": "Activer",
        "btn_promo": "Lien & Promo",
        "btn_faq": "FAQ",
        "btn_support": "Support",
        "btn_admin": "Contacter Admin",
        "btn_lang": "FR / EN",
        "btn_back": "Retour",
        "btn_otc": "Paires OTC",
        "btn_crypto": "Paires Crypto",
        "btn_another": "Nouveau signal",
        "market_prompt": "Choisis le marche :",
        "pair_prompt": "Choisis une paire ({cat}) :",
        "tf_prompt": "Paire : {pair}\nChoisis le timeframe :",
        "wait_msg": "Attends le signal, frere • • •",
        "analyzing_msg": "Analyse {pair} [{tf}] • • •",
        "unlimited": "Illimite (Admin)",
        "trial_left": "{left} essai(s) gratuit(s) restant(s) sur {limit}",
        "active_vip": "Actif",
        "locked_msg": (
            "Tes 5 essais gratuits sont termines.\n"
            "Activation requise (10$ / 20$ selon formule).\n"
            "Envoie le code d'activation (ex: {code}) ou contacte @{admin}."
        ),
        "activated_ok": "Compte autorise immediatement.",
        "code_invalid": "Code invalide. Contacte @{admin}.",
        "faq_text": (
            "FAQ & Guides :\n"
            "1. Fonctionnement : le moteur combine 80% d'analyse technique et 20% de composante aleatoire.\n"
            "2. Heure de reference (UTC) : {utc_now}\n"
            "3. Timeframes : S15 offre souvent plus de stabilite que S5 ; surveille la paire choisie (ex: GBP/USD (OTC), CAD/JPY (OTC)).\n"
            "4. Gestion : garde des mises prudentes, evite de forcer apres une perte et garde a l'esprit qu'aucun signal n'est garanti a 100%."
        ),
        "support_text": "Support direct : @{admin}",
    },
    "en": {
        "choose_lang": "Choose a language / Choisis une langue :",
        "lang_set": "Language: English",
        "home_body": (
            "B2K Signal Engine\n"
            "Choose an option below.\n"
            "Note: every signal carries uncertainty."
        ),
        "btn_signal": "Get signal",
        "btn_account": "My account",
        "btn_activate": "Activate",
        "btn_promo": "Link & Promo",
        "btn_faq": "FAQ",
        "btn_support": "Support",
        "btn_admin": "Contact Admin",
        "btn_lang": "EN / FR",
        "btn_back": "Back",
        "btn_otc": "OTC Pairs",
        "btn_crypto": "Crypto Pairs",
        "btn_another": "Another signal",
        "market_prompt": "Choose market:",
        "pair_prompt": "Choose a pair ({cat}):",
        "tf_prompt": "Pair: {pair}\nChoose timeframe:",
        "wait_msg": "Wait for the signal, bro • • •",
        "analyzing_msg": "Analyzing {pair} [{tf}] • • •",
        "unlimited": "Unlimited (Admin)",
        "trial_left": "{left} free trial(s) left out of {limit}",
        "active_vip": "Active",
        "locked_msg": (
            "Your 5 free trials are used.\n"
            "Activation required ($10 / $20 plan).\n"
            "Send your activation code (e.g. {code}) or contact @{admin}."
        ),
        "activated_ok": "Account authorized immediately.",
        "code_invalid": "Invalid code. Contact @{admin}.",
        "faq_text": (
            "FAQ & Guides:\n"
            "1. How it works: 80% technical analysis + 20% random component.\n"
            "2. Reference time (UTC): {utc_now}\n"
            "3. Timeframes: S15 is often steadier than S5; watch your selected pair (e.g. GBP/USD (OTC), CAD/JPY (OTC)).\n"
            "4. Risk guide: use controlled sizing, avoid revenge trades, and remember no signal is 100% guaranteed."
        ),
        "support_text": "Direct support: @{admin}",
    },
}


# ───────────────────────────── Accès & Utilisateurs ─────────────────────────────
class AccessManager:
    def __init__(self):
        self.lang: dict[int, str] = {}
        self.used_trials: dict[int, int] = {}
        self.authorized: set[int] = set()
        self.awaiting_code: set[int] = set()

    def get_lang(self, uid: int) -> str:
        return self.lang.get(uid, "fr")

    def is_admin(self, uid: int, username: str | None) -> bool:
        return bool(username and username.lstrip("@").lower() == ADMIN_USERNAME.lower())

    def can_generate(self, uid: int, username: str | None) -> bool:
        if self.is_admin(uid, username) or uid in self.authorized:
            return True
        return self.used_trials.get(uid, 0) < FREE_TRIALS_LIMIT

    def consume_trial(self, uid: int, username: str | None):
        if not self.is_admin(uid, username) and uid not in self.authorized:
            self.used_trials[uid] = self.used_trials.get(uid, 0) + 1

    def status_label(self, uid: int, username: str | None) -> str:
        t = TEXTS[self.get_lang(uid)]
        if self.is_admin(uid, username):
            return t["unlimited"]
        if uid in self.authorized:
            return t["active_vip"]
        left = max(0, FREE_TRIALS_LIMIT - self.used_trials.get(uid, 0))
        return t["trial_left"].format(left=left, limit=FREE_TRIALS_LIMIT)


access = AccessManager()


# ───────────────────────────── Indicateurs & Moteur ─────────────────────────────
def sma(values: list[float], period: int) -> float | None:
    return sum(values[-period:]) / period if len(values) >= period else None


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
    gains = losses = 0.0
    for i in range(1, period + 1):
        d = values[i] - values[i - 1]
        gains += max(d, 0.0)
        losses += max(-d, 0.0)
    ag, al = gains / period, losses / period
    for i in range(period + 1, len(values)):
        d = values[i] - values[i - 1]
        ag = (ag * (period - 1) + max(d, 0.0)) / period
        al = (al * (period - 1) + max(-d, 0.0)) / period
    if al == 0.0:
        return 100.0
    return 100.0 - (100.0 / (1.0 + ag / al))


def macd(values: list[float], fast: int = 12, slow: int = 26, signal: int = 9):
    if len(values) < slow + signal:
        return None
    line = [a - b for a, b in zip(ema_series(values, fast), ema_series(values, slow))]
    sig = ema_series(line, signal)
    return line[-1], sig[-1], line[-1] - sig[-1]


def clamp(val: float, lo: float = -1.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, val))


class CandleBuilder:
    def __init__(self, tf_sec: int, maxlen: int = 200):
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
        return list(self.closes) + ([self._last] if self._last is not None else [])


class BinanceFeed:
    URL = "https://api.binance.com/api/v3/ticker/price"

    def __init__(self, symbols: list[str]):
        self.symbols = set(symbols)
        self.session: ClientSession | None = None

    async def fetch(self) -> dict[str, float]:
        if self.session is None or self.session.closed:
            self.session = ClientSession(
                timeout=ClientTimeout(total=4),
                headers={"User-Agent": "Mozilla/5.0"},
            )
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


@dataclass
class SignalResult:
    pair: str
    tf: str
    side: str  # "BUY" ou "SELL"
    prob_pct: float
    uncertainty: str


class SignalEngine:
    def __init__(self):
        self.feed = BinanceFeed(CRYPTO_PAIRS)
        self.candles = {
            pair: {tf: CandleBuilder(sec) for tf, sec in TIMEFRAMES.items()}
            for pair in ALL_PAIRS
        }
        self.prices: dict[str, float] = {
            "EUR/USD (OTC)": 1.08420,
            "AUD/USD (OTC)": 0.65310,
            "GBP/USD (OTC)": 1.26840,
            "USD/JPY (OTC)": 154.620,
            "EUR/CAD (OTC)": 1.51230,
            "CAD/JPY (OTC)": 102.240,
        }
        self._drift = {p: 0.0 for p in OTC_PAIRS}

    async def run(self):
        next_tick = time.monotonic()
        while True:
            now = time.time()
            for pair in OTC_PAIRS:
                scale = 0.00018 if "JPY" not in pair else 0.015
                self._drift[pair] = 0.85 * self._drift[pair] + random.gauss(0.0, scale * 0.35)
                px = max(0.0001, self.prices[pair] + self._drift[pair] + random.gauss(0.0, scale))
                self.prices[pair] = px
                for cb in self.candles[pair].values():
                    cb.push(now, px)

            try:
                c_px = await self.feed.fetch()
                if c_px:
                    self.prices.update(c_px)
                    for pair, px in c_px.items():
                        for cb in self.candles[pair].values():
                            cb.push(now, px)
            except Exception as exc:
                log.warning("Erreur flux crypto : %s", exc)

            next_tick += 1.0
            await asyncio.sleep(max(0.0, next_tick - time.monotonic()))

    def generate(self, pair: str, tf: str, lang: str) -> SignalResult:
        closes = self.candles[pair][tf].series()
        comps: list[float] = []
        r_val = rsi(closes, period=min(14, max(2, len(closes) - 1))) if len(closes) >= 4 else None
        m_val = macd(closes) if len(closes) >= 20 else None
        s_f = sma(closes, 5) if len(closes) >= 5 else None
        s_s = sma(closes, 12) if len(closes) >= 12 else None

        if len(closes) >= 2:
            diffs = [closes[i] - closes[i - 1] for i in range(max(1, len(closes) - 12), len(closes))]
            vol = math.sqrt(sum(d * d for d in diffs) / len(diffs)) or 1e-9
            comps.append(clamp(math.tanh(sum(diffs[-3:]) / vol)))
            if r_val is not None:
                comps.append(clamp((50.0 - r_val) / 25.0))
            if m_val is not None:
                comps.append(clamp(math.tanh(m_val[2] / vol)))
            if s_f is not None and s_s is not None:
                comps.append(clamp(math.tanh((s_f - s_s) / vol)))

        tech = sum(comps) / len(comps) if comps else 0.0
        rnd = random.uniform(-1.0, 1.0)

        # 80 % analyse technique + 20 % composante aléatoire
        score = 0.80 * tech + 0.20 * rnd
        side = "BUY" if score >= 0.0 else "SELL"
        prob = round(54.0 + min(1.0, abs(score)) * 24.0, 1)

        if lang == "en":
            unc = "Uncertainty: short-term market noise and reversals remain possible."
        else:
            unc = "Incertitude : le bruit court terme et les retournements restent possibles."

        return SignalResult(pair, tf, side, prob, unc)


engine = SignalEngine()


# ───────────────────────────── Serveur Web ─────────────────────────────
async def index(request: web.Request):
    html_file = Path(__file__).parent / "webapp" / "index.html"
    if html_file.exists():
        return web.FileResponse(html_file)
    return web.Response(text="B2K Bot OK", content_type="text/plain")


# ───────────────────────────── Claviers ─────────────────────────────
NO_PREVIEW = LinkPreviewOptions(is_disabled=True)


def lang_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Francais", callback_data="set_lang:fr"),
                InlineKeyboardButton(text="English", callback_data="set_lang:en"),
            ]
        ]
    )


def main_menu_keyboard(lang: str) -> InlineKeyboardMarkup:
    t = TEXTS[lang]
    rows: list[list[InlineKeyboardButton]] = [
        [InlineKeyboardButton(text=t["btn_signal"], callback_data="nav:market")],
        [
            InlineKeyboardButton(text=t["btn_account"], callback_data="nav:account"),
            InlineKeyboardButton(text=t["btn_activate"], callback_data="nav:activate"),
        ],
        [
            InlineKeyboardButton(text=t["btn_promo"], callback_data="nav:promo"),
            InlineKeyboardButton(text=t["btn_admin"], url=ADMIN_URL),
        ],
        [
            InlineKeyboardButton(text=t["btn_faq"], callback_data="nav:faq"),
            InlineKeyboardButton(text=t["btn_support"], callback_data="nav:support"),
        ],
        [InlineKeyboardButton(text=t["btn_lang"], callback_data="nav:lang")],
    ]
    if WEBAPP_URL.startswith("https://"):
        rows.append([InlineKeyboardButton(text="Mini-App", web_app=WebAppInfo(url=WEBAPP_URL))])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def market_keyboard(lang: str) -> InlineKeyboardMarkup:
    t = TEXTS[lang]
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text=t["btn_otc"], callback_data="cat:OTC"),
                InlineKeyboardButton(text=t["btn_crypto"], callback_data="cat:CRYPTO"),
            ],
            [InlineKeyboardButton(text=t["btn_back"], callback_data="nav:home")],
        ]
    )


def pairs_keyboard(cat: str, lang: str) -> InlineKeyboardMarkup:
    t = TEXTS[lang]
    plist = OTC_PAIRS if cat == "OTC" else CRYPTO_PAIRS
    rows: list[list[InlineKeyboardButton]] = []
    for i in range(0, len(plist), 2):
        r = [InlineKeyboardButton(text=plist[i], callback_data=f"pair:{plist[i]}")]
        if i + 1 < len(plist):
            r.append(InlineKeyboardButton(text=plist[i + 1], callback_data=f"pair:{plist[i + 1]}"))
        rows.append(r)
    rows.append([InlineKeyboardButton(text=t["btn_back"], callback_data="nav:market")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def tf_keyboard(pair: str, lang: str) -> InlineKeyboardMarkup:
    t = TEXTS[lang]
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="S5", callback_data=f"sig:{pair}:S5"),
                InlineKeyboardButton(text="S15", callback_data=f"sig:{pair}:S15"),
            ],
            [
                InlineKeyboardButton(text="S30", callback_data=f"sig:{pair}:S30"),
                InlineKeyboardButton(text="M1", callback_data=f"sig:{pair}:M1"),
            ],
            [InlineKeyboardButton(text=t["btn_back"], callback_data="nav:market")],
        ]
    )


def after_signal_keyboard(pair: str, tf: str, lang: str) -> InlineKeyboardMarkup:
    t = TEXTS[lang]
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=t["btn_another"], callback_data=f"sig:{pair}:{tf}")],
            [
                InlineKeyboardButton(text=t["btn_signal"], callback_data="nav:market"),
                InlineKeyboardButton(text=t["btn_admin"], url=ADMIN_URL),
            ],
            [InlineKeyboardButton(text=t["btn_back"], callback_data="nav:home")],
        ]
    )


def back_home_keyboard(lang: str) -> InlineKeyboardMarkup:
    t = TEXTS[lang]
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=t["btn_admin"], url=ADMIN_URL)],
            [InlineKeyboardButton(text=t["btn_back"], callback_data="nav:home")],
        ]
    )


def parse_photo_slot_command(text: str) -> str | None:
    cleaned = text.strip().lower()
    if cleaned in ("/set_photo_buy", "/set photo buy", "set photo buy"):
        return "buy"
    if cleaned in ("/set_photo_sell", "/set photo sell", "set photo sell"):
        return "sell"
    if cleaned in ("/set_photo_menu", "/set photo menu", "set photo menu"):
        return "menu"
    return None


# ───────────────────────────── Bot Telegram ─────────────────────────────
async def run_bot():
    if not BOT_TOKEN:
        log.error("BOT_TOKEN manquant dans Environment.")
        return

    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher()

    @dp.message(CommandStart())
    async def cmd_start(message: Message):
        uid = message.from_user.id if message.from_user else 0
        access.awaiting_code.discard(uid)
        media_store.awaiting_slot.pop(uid, None)
        await message.answer(
            TEXTS["fr"]["choose_lang"],
            reply_markup=lang_keyboard(),
            link_preview_options=NO_PREVIEW,
        )

    @dp.message(Command("activate"))
    async def cmd_activate_admin(message: Message):
        uid = message.from_user.id if message.from_user else 0
        uname = message.from_user.username if message.from_user else None
        if not access.is_admin(uid, uname):
            return
        parts = (message.text or "").split()
        if len(parts) < 2 or not parts[1].isdigit():
            await message.answer("Usage : /activate <user_id>")
            return
        target_id = int(parts[1])
        access.authorized.add(target_id)
        await message.answer(f"Utilisateur {target_id} autorise immediatement.")

    @dp.message(F.photo)
    async def on_photo_upload(message: Message):
        uid = message.from_user.id if message.from_user else 0
        uname = message.from_user.username if message.from_user else None
        slot = media_store.awaiting_slot.pop(uid, None)
        if not slot:
            return
        if not access.is_admin(uid, uname) and uid not in access.authorized:
            await message.answer("Acces reserve a l'admin.")
            return
        largest = message.photo[-1]
        media_store.file_ids[slot] = largest.file_id
        buf = io.BytesIO()
        await bot.download(largest.file_id, destination=buf)
        (ASSETS_DIR / f"{slot}.jpg").write_bytes(buf.getvalue())
        await message.answer(f"Photo '{slot}' enregistree.")

    @dp.message(F.text)
    async def on_text_msg(message: Message):
        uid = message.from_user.id if message.from_user else 0
        uname = message.from_user.username if message.from_user else None
        lang = access.get_lang(uid)
        t = TEXTS[lang]
        txt = (message.text or "").strip()

        slot = parse_photo_slot_command(txt)
        if slot:
            media_store.awaiting_slot[uid] = slot
            await message.answer(f"Envoie maintenant ta photo pour '{slot}' depuis ta galerie.")
            return

        if uid in access.awaiting_code:
            if txt == ACTIVATION_CODE:
                access.authorized.add(uid)
                access.awaiting_code.discard(uid)
                await message.answer(
                    t["activated_ok"],
                    reply_markup=main_menu_keyboard(lang),
                    link_preview_options=NO_PREVIEW,
                )
            else:
                await message.answer(
                    t["code_invalid"].format(admin=ADMIN_USERNAME),
                    reply_markup=back_home_keyboard(lang),
                    link_preview_options=NO_PREVIEW,
                )

    @dp.callback_query(F.data.startswith("set_lang:"))
    async def cb_set_lang(callback: CallbackQuery):
        uid = callback.from_user.id
        lang = callback.data.split(":", 1)[1]
        if lang not in ("fr", "en"):
            lang = "fr"
        access.lang[uid] = lang
        t = TEXTS[lang]
        await callback.answer(t["lang_set"])
        photo = await get_photo_input(bot, "menu")
        await callback.message.answer_photo(
            photo=photo,
            caption=t["home_body"],
            reply_markup=main_menu_keyboard(lang),
        )

    @dp.callback_query(F.data.startswith("nav:"))
    async def cb_nav(callback: CallbackQuery):
        uid = callback.from_user.id
        uname = callback.from_user.username
        lang = access.get_lang(uid)
        t = TEXTS[lang]
        dest = callback.data.split(":", 1)[1]
        await callback.answer()

        if dest == "lang":
            await callback.message.answer(
                t["choose_lang"],
                reply_markup=lang_keyboard(),
                link_preview_options=NO_PREVIEW,
            )
        elif dest == "home":
            access.awaiting_code.discard(uid)
            photo = await get_photo_input(bot, "menu")
            await callback.message.answer_photo(
                photo=photo,
                caption=t["home_body"],
                reply_markup=main_menu_keyboard(lang),
            )
        elif dest == "market":
            if not access.can_generate(uid, uname):
                access.awaiting_code.add(uid)
                await callback.message.answer(
                    t["locked_msg"].format(code=ACTIVATION_CODE, admin=ADMIN_USERNAME),
                    reply_markup=back_home_keyboard(lang),
                    link_preview_options=NO_PREVIEW,
                )
                return
            await callback.message.answer(
                t["market_prompt"],
                reply_markup=market_keyboard(lang),
                link_preview_options=NO_PREVIEW,
            )
        elif dest == "account":
            st = access.status_label(uid, uname)
            await callback.message.answer(
                f"ID: {uid}\nStatus: {st}\nPromo: {PROMO_CODE}\nLink: {PARTNER_LINK}",
                reply_markup=back_home_keyboard(lang),
                link_preview_options=NO_PREVIEW,
            )
        elif dest == "promo":
            await callback.message.answer(
                f"Promo: {PROMO_CODE}\nLink: {PARTNER_LINK}",
                reply_markup=back_home_keyboard(lang),
                link_preview_options=NO_PREVIEW,
            )
        elif dest == "activate":
            access.awaiting_code.add(uid)
            await callback.message.answer(
                t["locked_msg"].format(code=ACTIVATION_CODE, admin=ADMIN_USERNAME),
                reply_markup=back_home_keyboard(lang),
                link_preview_options=NO_PREVIEW,
            )
        elif dest == "faq":
            utc_now = datetime.datetime.now(datetime.timezone.utc).strftime("%H:%M:%S")
            await callback.message.answer(
                t["faq_text"].format(utc_now=utc_now),
                reply_markup=back_home_keyboard(lang),
                link_preview_options=NO_PREVIEW,
            )
        elif dest == "support":
            await callback.message.answer(
                t["support_text"].format(admin=ADMIN_USERNAME),
                reply_markup=back_home_keyboard(lang),
                link_preview_options=NO_PREVIEW,
            )

    @dp.callback_query(F.data.startswith("cat:"))
    async def cb_cat(callback: CallbackQuery):
        uid = callback.from_user.id
        lang = access.get_lang(uid)
        t = TEXTS[lang]
        cat = callback.data.split(":", 1)[1]
        await callback.answer()
        await callback.message.answer(
            t["pair_prompt"].format(cat=cat),
            reply_markup=pairs_keyboard(cat, lang),
            link_preview_options=NO_PREVIEW,
        )

    @dp.callback_query(F.data.startswith("pair:"))
    async def cb_pair(callback: CallbackQuery):
        uid = callback.from_user.id
        lang = access.get_lang(uid)
        t = TEXTS[lang]
        pair = callback.data.split(":", 1)[1]
        await callback.answer()
        await callback.message.answer(
            t["tf_prompt"].format(pair=pair),
            reply_markup=tf_keyboard(pair, lang),
            link_preview_options=NO_PREVIEW,
        )

    @dp.callback_query(F.data.startswith("sig:"))
    async def cb_sig(callback: CallbackQuery):
        uid = callback.from_user.id
        uname = callback.from_user.username
        lang = access.get_lang(uid)
        t = TEXTS[lang]

        if not access.can_generate(uid, uname):
            access.awaiting_code.add(uid)
            await callback.answer()
            await callback.message.answer(
                t["locked_msg"].format(code=ACTIVATION_CODE, admin=ADMIN_USERNAME),
                reply_markup=back_home_keyboard(lang),
                link_preview_options=NO_PREVIEW,
            )
            return

        _, pair, tf = callback.data.split(":", 2)
        access.consume_trial(uid, uname)
        await callback.answer(t["wait_msg"])

        wait_msg = await callback.message.answer(t["wait_msg"], link_preview_options=NO_PREVIEW)
        await asyncio.sleep(0.8)
        await wait_msg.edit_text(t["analyzing_msg"].format(pair=pair, tf=tf))
        await asyncio.sleep(0.8)

        sig = engine.generate(pair, tf, lang)
        px = engine.prices.get(pair)
        px_fmt = f"{px:.5f}" if px is not None and px < 50 else (f"{px:.2f}" if px is not None else "N/A")

        photo_slot = "buy" if sig.side == "BUY" else "sell"
        banner = await get_photo_input(bot, photo_slot)

        caption = (
            f"{sig.side}\n"
            f"Pair: {sig.pair} | {sig.tf}\n"
            f"Prob: {sig.prob_pct}% | Price: {px_fmt}\n"
            f"{sig.uncertainty}"
        )
        await callback.message.answer_photo(
            photo=banner,
            caption=caption,
            reply_markup=after_signal_keyboard(pair, tf, lang),
        )

    try:
        await dp.start_polling(bot)
    finally:
        await engine.feed.close()
        await bot.session.close()


async def main():
    app = web.Application()
    app.router.add_get("/", index)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", PORT).start()
    log.info("Serveur démarré sur le port %s", PORT)
    await asyncio.gather(engine.run(), run_bot())


if __name__ == "__main__":
    asyncio.run(main())
