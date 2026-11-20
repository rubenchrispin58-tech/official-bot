import asyncio
import datetime
import hashlib
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
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    LinkPreviewOptions,
    Message,
    WebAppInfo,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
log = logging.getLogger("b2k_pro_bot")

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
WEBAPP_URL = os.getenv("WEBAPP_URL", "").strip()
PORT = int(os.getenv("PORT", "10000"))

ADMIN_USERNAME = "b2k_ruben"
ADMIN_URL = f"https://t.me/{ADMIN_USERNAME}"
PROMO_CODE = "FRIENDXYZLOERADB"
PARTNER_LINK = "https://pocket-friends.co/r/xyzloeradb"

FREE_TRIALS_LIMIT = 5
ACTIVATION_CODE = os.getenv("ACTIVATION_CODE", "B2K20").strip()

OTC_PAIRS = [
    "EUR/USD (OTC)",
    "AUD/USD (OTC)",
    "USD/JPY (OTC)",
    "GBP/USD (OTC)",
    "EUR/CAD (OTC)",
    "CAD/JPY (OTC)",
]
CRYPTO_PAIRS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT"]
ALL_PAIRS = OTC_PAIRS + CRYPTO_PAIRS
TIMEFRAMES = {"S5": 5, "S15": 15, "S30": 30, "M1": 60}


# ───────────────────────────── Textes FR / EN ─────────────────────────────
TEXTS = {
    "fr": {
        "choose_lang": "Choisis une langue / Choose a language :",
        "lang_set": "Langue definie sur : Francais.",
        "home_title": "B2K Signal Engine",
        "home_body": (
            "Modele : 70% analyse technique / 30% aleatoire\n"
            "Essais gratuits : 5 signaux\n"
            "Code promo : {promo}\n"
            "Admin : @{admin}\n\n"
            "Note : les signaux comportent toujours une part d'incertitude."
        ),
        "btn_signal": "Get signal",
        "btn_account": "Mon compte",
        "btn_activate": "Activer / Depot",
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
        "analyzing_msg": "Analyse {pair} [{tf}] (70% tech / 30% random) • • •",
        "unlimited": "Illimite (Admin)",
        "trial_left": "{left} essai(s) gratuit(s) restant(s) sur {limit}",
        "active_vip": "Actif (Autorise)",
        "locked_msg": (
            "Tes 5 essais gratuits sont utilises.\n"
            "Activation requise (10$ / 20$ selon formule).\n\n"
            "Pour activer immediatement sans setup :\n"
            "Envoie le code d'activation dans le chat (ex: {code}) ou contacte @{admin}."
        ),
        "activated_ok": "Compte autorise immediatement ! Tu as maintenant acces aux signaux.",
        "code_invalid": "Code invalide. Verifie le code ou contacte @{admin}.",
        "faq_text": (
            "FAQ :\n"
            "- 5 essais gratuits pour tester le bot.\n"
            "- 70% indicateurs techniques + 30% composante aleatoire.\n"
            "- Aucun signal n'est garanti a 100%."
        ),
        "support_text": "Support & contact direct : @{admin}",
    },
    "en": {
        "choose_lang": "Choose a language / Choisis une langue :",
        "lang_set": "Language set to: English.",
        "home_title": "B2K Signal Engine",
        "home_body": (
            "Model: 70% technical analysis / 30% random\n"
            "Free trials: 5 signals\n"
            "Promo code: {promo}\n"
            "Admin: @{admin}\n\n"
            "Note: short-term signals always carry uncertainty."
        ),
        "btn_signal": "Get signal",
        "btn_account": "My account",
        "btn_activate": "Activate / Deposit",
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
        "analyzing_msg": "Analyzing {pair} [{tf}] (70% tech / 30% random) • • •",
        "unlimited": "Unlimited (Admin)",
        "trial_left": "{left} free trial(s) left out of {limit}",
        "active_vip": "Active (Authorized)",
        "locked_msg": (
            "Your 5 free trials have been used.\n"
            "Activation required ($10 / $20 plan).\n\n"
            "Instant activation with zero setup:\n"
            "Send your activation code here (e.g. {code}) or contact @{admin}."
        ),
        "activated_ok": "Account authorized immediately! You can now generate signals.",
        "code_invalid": "Invalid code. Check the code or contact @{admin}.",
        "faq_text": (
            "FAQ:\n"
            "- 5 free trials for new users.\n"
            "- 70% technical indicators + 30% random component.\n"
            "- No signal is 100% guaranteed."
        ),
        "support_text": "Direct support: @{admin}",
    },
}


# ───────────────────────────── État Utilisateur & Accès ─────────────────────────────
class AccessManager:
    def __init__(self):
        self.lang: dict[int, str] = {}
        self.used_trials: dict[int, int] = {}
        self.authorized: set[int] = set()
        self.awaiting_code: set[int] = set()

    def get_lang(self, user_id: int) -> str:
        return self.lang.get(user_id, "fr")

    def is_admin(self, user_id: int, username: str | None) -> bool:
        if username and username.lstrip("@").lower() == ADMIN_USERNAME.lower():
            return True
        return user_id in self.authorized and user_id == 0

    def can_generate(self, user_id: int, username: str | None) -> bool:
        if self.is_admin(user_id, username) or user_id in self.authorized:
            return True
        return self.used_trials.get(user_id, 0) < FREE_TRIALS_LIMIT

    def consume_trial(self, user_id: int, username: str | None):
        if not self.is_admin(user_id, username) and user_id not in self.authorized:
            self.used_trials[user_id] = self.used_trials.get(user_id, 0) + 1

    def status_label(self, user_id: int, username: str | None) -> str:
        lang = self.get_lang(user_id)
        t = TEXTS[lang]
        if self.is_admin(user_id, username):
            return t["unlimited"]
        if user_id in self.authorized:
            return t["active_vip"]
        left = max(0, FREE_TRIALS_LIMIT - self.used_trials.get(user_id, 0))
        return t["trial_left"].format(left=left, limit=FREE_TRIALS_LIMIT)


access = AccessManager()


# ───────────────────────────── Indicateurs & Flux ─────────────────────────────
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
class SignalOutput:
    pair: str
    tf: str
    direction: str
    prob_pct: float
    tech_score: float
    rand_score: float
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
            "USD/JPY (OTC)": 154.620,
            "GBP/USD (OTC)": 1.26840,
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

    def generate(self, pair: str, tf: str, lang: str) -> SignalOutput:
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
        score = 0.70 * tech + 0.30 * rnd
        direction = "BUY" if score >= 0.0 else "SELL"
        prob = round(53.0 + min(1.0, abs(score)) * 24.0, 1)

        if lang == "en":
            unc = "Uncertainty active: 70% technical / 30% random, market can reverse quickly."
        else:
            unc = "Incertitude active : 70% technique / 30% aleatoire, retournement possible."

        return SignalOutput(pair, tf, direction, prob, round(tech, 3), round(rnd, 3), unc)


engine = SignalEngine()


# ───────────────────────────── Web Server ─────────────────────────────
async def index(request: web.Request):
    html_file = Path(__file__).parent / "webapp" / "index.html"
    if html_file.exists():
        return web.FileResponse(html_file)
    return web.Response(text="B2K Bot Server OK", content_type="text/plain")


# ───────────────────────────── Claviers Clean ─────────────────────────────
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
            InlineKeyboardButton(text=t["btn_promo"], url=PARTNER_LINK),
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


def signal_done_keyboard(pair: str, tf: str, lang: str) -> InlineKeyboardMarkup:
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

    @dp.message(F.text)
    async def on_text_input(message: Message):
        uid = message.from_user.id if message.from_user else 0
        lang = access.get_lang(uid)
        t = TEXTS[lang]
        txt = (message.text or "").strip()
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
        await callback.message.edit_text(
            f"{t['home_title']}\n\n{t['home_body'].format(promo=PROMO_CODE, admin=ADMIN_USERNAME)}",
            reply_markup=main_menu_keyboard(lang),
            link_preview_options=NO_PREVIEW,
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
            await callback.message.edit_text(
                t["choose_lang"],
                reply_markup=lang_keyboard(),
                link_preview_options=NO_PREVIEW,
            )
        elif dest == "home":
            access.awaiting_code.discard(uid)
            await callback.message.edit_text(
                f"{t['home_title']}\n\n{t['home_body'].format(promo=PROMO_CODE, admin=ADMIN_USERNAME)}",
                reply_markup=main_menu_keyboard(lang),
                link_preview_options=NO_PREVIEW,
            )
        elif dest == "market":
            if not access.can_generate(uid, uname):
                access.awaiting_code.add(uid)
                await callback.message.edit_text(
                    t["locked_msg"].format(code=ACTIVATION_CODE, admin=ADMIN_USERNAME),
                    reply_markup=back_home_keyboard(lang),
                    link_preview_options=NO_PREVIEW,
                )
                return
            await callback.message.edit_text(
                t["market_prompt"],
                reply_markup=market_keyboard(lang),
                link_preview_options=NO_PREVIEW,
            )
        elif dest == "account":
            st = access.status_label(uid, uname)
            await callback.message.edit_text(
                f"ID: {uid}\nStatus: {st}\nPromo: {PROMO_CODE}",
                reply_markup=back_home_keyboard(lang),
                link_preview_options=NO_PREVIEW,
            )
        elif dest == "activate":
            access.awaiting_code.add(uid)
            await callback.message.edit_text(
                t["locked_msg"].format(code=ACTIVATION_CODE, admin=ADMIN_USERNAME),
                reply_markup=back_home_keyboard(lang),
                link_preview_options=NO_PREVIEW,
            )
        elif dest == "faq":
            await callback.message.edit_text(
                t["faq_text"],
                reply_markup=back_home_keyboard(lang),
                link_preview_options=NO_PREVIEW,
            )
        elif dest == "support":
            await callback.message.edit_text(
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
        await callback.message.edit_text(
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
        await callback.message.edit_text(
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
            await callback.message.edit_text(
                t["locked_msg"].format(code=ACTIVATION_CODE, admin=ADMIN_USERNAME),
                reply_markup=back_home_keyboard(lang),
                link_preview_options=NO_PREVIEW,
            )
            return

        _, pair, tf = callback.data.split(":", 2)
        access.consume_trial(uid, uname)
        await callback.answer(t["wait_msg"])

        wait_msg = await callback.message.answer(
            t["wait_msg"],
            link_preview_options=NO_PREVIEW,
        )
        await asyncio.sleep(0.9)
        await wait_msg.edit_text(
            t["analyzing_msg"].format(pair=pair, tf=tf),
            link_preview_options=NO_PREVIEW,
        )
        await asyncio.sleep(0.9)

        sig = engine.generate(pair, tf, lang)
        now_utc = datetime.datetime.now(datetime.timezone.utc).strftime("%H:%M:%S")
        px = engine.prices.get(pair)
        px_fmt = f"{px:.5f}" if px is not None and px < 50 else (f"{px:.2f}" if px is not None else "N/A")

        report = (
            f"{sig.pair} | {sig.tf}\n"
            f"Direction: {sig.direction}\n"
            f"Prob: {sig.prob_pct}%\n"
            f"Price: {px_fmt} | UTC: {now_utc}\n"
            f"Mix: 70% tech ({sig.tech_score}) + 30% rand ({sig.rand_score})\n"
            f"{sig.uncertainty}\n"
            f"Promo: {PROMO_CODE}"
        )
        await wait_msg.edit_text(
            report,
            reply_markup=signal_done_keyboard(pair, tf, lang),
            link_preview_options=NO_PREVIEW,
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
