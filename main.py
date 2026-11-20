import asyncio
import datetime
import logging
import math
import os
import random
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path

from aiohttp import web
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    LinkPreviewOptions,
    Message,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
log = logging.getLogger("b2k_clean_bot")

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
PORT = int(os.getenv("PORT", "10000"))

ADMIN_USERNAME = "b2k_ruben"
ADMIN_URL = f"https://t.me/{ADMIN_USERNAME}"
PROMO_CODE = "FRIENDXYZLOERADB"
PARTNER_LINK = "https://pocket-friends.co/r/xyzloeradb"

FREE_TRIALS_LIMIT = 5

OTC_PAIRS = [
    "GBP/USD OTC",
    "AED/CNY OTC",
    "AUD/CAD OTC",
    "NZD/CHF OTC",
    "EUR/USD OTC",
    "GBP/JPY OTC",
    "EUR/GBP OTC",
]
MARKET_PICKS = [
    "Bitcoin",
    "Ethereum",
    "100 GBP",
    "CAC40",
]
ALL_PAIRS = OTC_PAIRS + MARKET_PICKS
TIMEFRAMES = {"S5": 5, "S15": 15, "S30": 30, "M1": 60}


# ───────────────────────────── Auto-Suppression des Anciens Messages ─────────────────────────────
class ChatCleaner:
    def __init__(self):
        self.last_bot_msg: dict[int, int] = {}

    async def purge_previous(self, bot: Bot, chat_id: int):
        prev_id = self.last_bot_msg.get(chat_id)
        if prev_id:
            try:
                await bot.delete_message(chat_id=chat_id, message_id=prev_id)
            except Exception:
                pass

    async def send_clean(
        self,
        bot: Bot,
        chat_id: int,
        text: str,
        reply_markup: InlineKeyboardMarkup | None = None,
    ) -> Message:
        await self.purge_previous(bot, chat_id)
        msg = await bot.send_message(
            chat_id=chat_id,
            text=text,
            reply_markup=reply_markup,
            link_preview_options=LinkPreviewOptions(is_disabled=True),
        )
        self.last_bot_msg[chat_id] = msg.message_id
        return msg

    async def edit_clean(
        self,
        bot: Bot,
        chat_id: int,
        message_id: int,
        text: str,
        reply_markup: InlineKeyboardMarkup | None = None,
    ) -> Message:
        msg = await bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text=text,
            reply_markup=reply_markup,
            link_preview_options=LinkPreviewOptions(is_disabled=True),
        )
        self.last_bot_msg[chat_id] = msg.message_id
        return msg


cleaner = ChatCleaner()


# ───────────────────────────── Accès & Utilisateurs (/add /del) ─────────────────────────────
class AccessManager:
    def __init__(self):
        self.lang: dict[int, str] = {}
        self.used_trials: dict[int, int] = {}
        self.authorized_ids: set[int] = set()

    def get_lang(self, uid: int) -> str:
        return self.lang.get(uid, "fr")

    def is_admin(self, username: str | None) -> bool:
        return bool(username and username.lstrip("@").lower() == ADMIN_USERNAME.lower())

    def add_user(self, target_id: int):
        self.authorized_ids.add(target_id)

    def del_user(self, target_id: int):
        self.authorized_ids.discard(target_id)

    def can_generate(self, uid: int, username: str | None) -> bool:
        if self.is_admin(username) or uid in self.authorized_ids:
            return True
        return self.used_trials.get(uid, 0) < FREE_TRIALS_LIMIT

    def consume_trial(self, uid: int, username: str | None):
        if not self.is_admin(username) and uid not in self.authorized_ids:
            self.used_trials[uid] = self.used_trials.get(uid, 0) + 1

    def status_text(self, uid: int, username: str | None, lang: str) -> str:
        if self.is_admin(username):
            return "Illimite (Admin)" if lang == "fr" else "Unlimited (Admin)"
        if uid in self.authorized_ids:
            return "Actif (Autorise)" if lang == "fr" else "Active (Authorized)"
        left = max(0, FREE_TRIALS_LIMIT - self.used_trials.get(uid, 0))
        if lang == "en":
            return f"{left} free trial(s) left out of {FREE_TRIALS_LIMIT}"
        return f"{left} essai(s) gratuit(s) restant(s) sur {FREE_TRIALS_LIMIT}"


access = AccessManager()


# ───────────────────────────── Analyse Technique 80% + Random 20% ─────────────────────────────
def compute_ema(values: list[float], period: int) -> float | None:
    if len(values) < period:
        return None
    k = 2.0 / (period + 1.0)
    val = sum(values[:period]) / period
    for px in values[period:]:
        val = px * k + val * (1.0 - k)
    return val


def compute_rsi(values: list[float], period: int = 10) -> float | None:
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


def clamp(x: float, lo: float = -1.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


class SeriesTracker:
    def __init__(self, tf_sec: int, seed_val: float, step_scale: float, maxlen: int = 120):
        self.tf_sec = tf_sec
        self.step_scale = step_scale
        self.closes: deque[float] = deque(maxlen=maxlen)
        self._bucket: int | None = None
        self._cur: float = seed_val
        self._trend: float = 0.0
        for _ in range(18):
            self._step()
            self.closes.append(self._cur)

    def _step(self):
        self._trend = 0.88 * self._trend + random.gauss(0.0, self.step_scale * 0.25)
        self._cur = max(0.01, self._cur + self._trend + random.gauss(0.0, self.step_scale))

    def tick(self, ts: float):
        self._step()
        bucket = int(ts) // self.tf_sec
        if self._bucket is None:
            self._bucket = bucket
        elif bucket != self._bucket:
            self.closes.append(self._cur)
            self._bucket = bucket

    def series(self) -> list[float]:
        return list(self.closes) + [self._cur]


@dataclass
class SignalCard:
    pair: str
    tf: str
    action: str  # "BUY" ou "SELL"
    prob_pct: float
    trend_label: str
    uncertainty: str


class MarketAnalyzer:
    SEEDS = {
        "GBP/USD OTC": (1.3380, 0.00022),
        "AED/CNY OTC": (1.9640, 0.00025),
        "AUD/CAD OTC": (0.9120, 0.00020),
        "NZD/CHF OTC": (0.5210, 0.00018),
        "EUR/USD OTC": (1.0840, 0.00020),
        "GBP/JPY OTC": (196.40, 0.035),
        "EUR/GBP OTC": (0.8540, 0.00016),
        "Bitcoin": (94500.0, 45.0),
        "Ethereum": (3180.0, 4.5),
        "100 GBP": (8240.0, 2.2),
        "CAC40": (7420.0, 1.8),
    }

    def __init__(self):
        self.trackers: dict[str, dict[str, SeriesTracker]] = {}
        for pair in ALL_PAIRS:
            base, scale = self.SEEDS[pair]
            tf_mult = {"S5": 0.65, "S15": 1.0, "S30": 1.35, "M1": 1.75}
            self.trackers[pair] = {
                tf: SeriesTracker(sec, base, scale * tf_mult[tf])
                for tf, sec in TIMEFRAMES.items()
            }

    async def run(self):
        next_t = time.monotonic()
        while True:
            now = time.time()
            for pair_map in self.trackers.values():
                for tr in pair_map.values():
                    tr.tick(now)
            next_t += 1.0
            await asyncio.sleep(max(0.0, next_t - time.monotonic()))

    def analyze(self, pair: str, tf: str, lang: str) -> SignalCard:
        closes = self.trackers[pair][tf].series()
        diffs = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
        vol = math.sqrt(sum(d * d for d in diffs[-12:]) / max(1, len(diffs[-12:]))) or 1e-9

        ema_f = compute_ema(closes, 5)
        ema_s = compute_ema(closes, 13)
        r_val = compute_rsi(closes, 10)

        tech_signals: list[float] = []
        if ema_f is not None and ema_s is not None:
            tech_signals.append(clamp(math.tanh((ema_f - ema_s) / vol)))
        if r_val is not None:
            tech_signals.append(clamp((50.0 - r_val) / 22.0))
        if diffs:
            tech_signals.append(clamp(math.tanh(sum(diffs[-3:]) / vol)))

        tech_score = sum(tech_signals) / len(tech_signals) if tech_signals else 0.0

        # 20 % aléatoire orienté selon la tendance de marché détectée
        trend_dir = 1.0 if tech_score >= 0.0 else -1.0
        rand_score = clamp(trend_dir * abs(random.gauss(0.35, 0.45)) + random.uniform(-0.35, 0.35))

        combined = 0.80 * tech_score + 0.20 * rand_score
        action = "BUY" if combined >= 0.0 else "SELL"
        prob = round(55.0 + min(1.0, abs(combined)) * 23.0, 1)

        if lang == "en":
            if tech_score > 0.12:
                trend_txt = "Bullish trend"
            elif tech_score < -0.12:
                trend_txt = "Bearish trend"
            else:
                trend_txt = "Range / sideways"
            unc = "Uncertainty: market noise and reversals remain possible."
        else:
            if tech_score > 0.12:
                trend_txt = "Tendance haussiere"
            elif tech_score < -0.12:
                trend_txt = "Tendance baissiere"
            else:
                trend_txt = "Zone de range"
            unc = "Incertitude : les retournements et le bruit de marche restent possibles."

        return SignalCard(pair, tf, action, prob, trend_txt, unc)


analyzer = MarketAnalyzer()


# ───────────────────────────── Serveur Web ─────────────────────────────
async def index(request: web.Request):
    html_file = Path(__file__).parent / "webapp" / "index.html"
    if html_file.exists():
        return web.FileResponse(html_file)
    return web.Response(text="B2K Bot Active", content_type="text/plain")


# ───────────────────────────── Claviers Stylés ─────────────────────────────
def lang_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🇫🇷 Francais", callback_data="lang:fr"),
                InlineKeyboardButton(text="🇬🇧 English", callback_data="lang:en"),
            ]
        ]
    )


def home_kb(lang: str) -> InlineKeyboardMarkup:
    if lang == "en":
        return InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="⚡ Get signal", callback_data="go:market")],
                [
                    InlineKeyboardButton(text="💎 Account", callback_data="go:account"),
                    InlineKeyboardButton(text="🔓 Activate", callback_data="go:activate"),
                ],
                [
                    InlineKeyboardButton(text="🔗 Link & Promo", url=PARTNER_LINK),
                    InlineKeyboardButton(text="👑 Admin", url=ADMIN_URL),
                ],
                [
                    InlineKeyboardButton(text="❓ FAQ", callback_data="go:faq"),
                    InlineKeyboardButton(text="🆘 Support", callback_data="go:support"),
                ],
                [InlineKeyboardButton(text="🌐 FR / EN", callback_data="go:lang")],
            ]
        )
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⚡ Get signal", callback_data="go:market")],
            [
                InlineKeyboardButton(text="💎 Mon compte", callback_data="go:account"),
                InlineKeyboardButton(text="🔓 Activer", callback_data="go:activate"),
            ],
            [
                InlineKeyboardButton(text="🔗 Lien & Promo", url=PARTNER_LINK),
                InlineKeyboardButton(text="👑 Admin", url=ADMIN_URL),
            ],
            [
                InlineKeyboardButton(text="❓ FAQ", callback_data="go:faq"),
                InlineKeyboardButton(text="🆘 Support", callback_data="go:support"),
            ],
            [InlineKeyboardButton(text="🌐 FR / EN", callback_data="go:lang")],
        ]
    )


def market_kb(lang: str) -> InlineKeyboardMarkup:
    back_txt = "⬅️ Back" if lang == "en" else "⬅️ Retour"
    otc_txt = "📊 OTC Pairs" if lang == "en" else "📊 Paires OTC"
    mkt_txt = "📈 Markets" if lang == "en" else "📈 Marches"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text=otc_txt, callback_data="cat:OTC"),
                InlineKeyboardButton(text=mkt_txt, callback_data="cat:MKT"),
            ],
            [InlineKeyboardButton(text=back_txt, callback_data="go:home")],
        ]
    )


def pairs_kb(cat: str, lang: str) -> InlineKeyboardMarkup:
    plist = OTC_PAIRS if cat == "OTC" else MARKET_PICKS
    rows: list[list[InlineKeyboardButton]] = []
    for i in range(0, len(plist), 2):
        r = [InlineKeyboardButton(text=f"▪️ {plist[i]}", callback_data=f"pair:{plist[i]}")]
        if i + 1 < len(plist):
            r.append(InlineKeyboardButton(text=f"▪️ {plist[i + 1]}", callback_data=f"pair:{plist[i + 1]}"))
        rows.append(r)
    back_txt = "⬅️ Markets" if lang == "en" else "⬅️ Marches"
    rows.append([InlineKeyboardButton(text=back_txt, callback_data="go:market")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def tf_kb(pair: str, lang: str) -> InlineKeyboardMarkup:
    back_txt = "⬅️ Pairs" if lang == "en" else "⬅️ Paires"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="⏱️ S5", callback_data=f"gen:{pair}:S5"),
                InlineKeyboardButton(text="⏱️ S15", callback_data=f"gen:{pair}:S15"),
            ],
            [
                InlineKeyboardButton(text="⏱️ S30", callback_data=f"gen:{pair}:S30"),
                InlineKeyboardButton(text="⏱️ M1", callback_data=f"gen:{pair}:M1"),
            ],
            [InlineKeyboardButton(text=back_txt, callback_data="go:market")],
        ]
    )


def result_kb(pair: str, tf: str, lang: str) -> InlineKeyboardMarkup:
    again_txt = "🔁 Another signal" if lang == "en" else "🔁 Nouveau signal"
    sig_txt = "⚡ Get signal" if lang == "en" else "⚡ Get signal"
    home_txt = "🏠 Menu" if lang == "en" else "🏠 Menu"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=again_txt, callback_data=f"gen:{pair}:{tf}")],
            [
                InlineKeyboardButton(text=sig_txt, callback_data="go:market"),
                InlineKeyboardButton(text="👑 Admin", url=ADMIN_URL),
            ],
            [InlineKeyboardButton(text=home_txt, callback_data="go:home")],
        ]
    )


def back_home_kb(lang: str) -> InlineKeyboardMarkup:
    home_txt = "⬅️ Menu" if lang == "en" else "⬅️ Menu"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="👑 Admin", url=ADMIN_URL)],
            [InlineKeyboardButton(text=home_txt, callback_data="go:home")],
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
    async def on_start(message: Message):
        cid = message.chat.id
        await cleaner.send_clean(
            bot,
            cid,
            "🌐 Choisis une langue / Choose a language :",
            reply_markup=lang_kb(),
        )

    @dp.message(Command("add"))
    async def on_add(message: Message):
        uname = message.from_user.username if message.from_user else None
        if not access.is_admin(uname):
            return
        parts = (message.text or "").split()
        if len(parts) < 2 or not parts[1].lstrip("-").isdigit():
            await cleaner.send_clean(bot, message.chat.id, "Usage : /add <ID>")
            return
        target_id = int(parts[1])
        access.add_user(target_id)
        await cleaner.send_clean(bot, message.chat.id, f"✅ ID {target_id} ajoute.")

    @dp.message(Command("del"))
    async def on_del(message: Message):
        uname = message.from_user.username if message.from_user else None
        if not access.is_admin(uname):
            return
        parts = (message.text or "").split()
        if len(parts) < 2 or not parts[1].lstrip("-").isdigit():
            await cleaner.send_clean(bot, message.chat.id, "Usage : /del <ID>")
            return
        target_id = int(parts[1])
        access.del_user(target_id)
        await cleaner.send_clean(bot, message.chat.id, f"🗑️ ID {target_id} retire.")

    @dp.callback_query(F.data.startswith("lang:"))
    async def cb_lang(callback: CallbackQuery):
        uid = callback.from_user.id
        cid = callback.message.chat.id
        lang = callback.data.split(":", 1)[1]
        access.lang[uid] = lang
        await callback.answer()
        if lang == "en":
            txt = (
                "✨ B2K Signal Engine\n\n"
                "• 5 free trials included\n"
                f"• Promo code: {PROMO_CODE}\n"
                f"• Link: {PARTNER_LINK}\n"
                f"• Admin: @{ADMIN_USERNAME}\n\n"
                "⚠️ Signals always carry uncertainty."
            )
        else:
            txt = (
                "✨ B2K Signal Engine\n\n"
                "• 5 essais gratuits inclus\n"
                f"• Code promo : {PROMO_CODE}\n"
                f"• Lien : {PARTNER_LINK}\n"
                f"• Admin : @{ADMIN_USERNAME}\n\n"
                "⚠️ Tout signal comporte une part d'incertitude."
            )
        await cleaner.send_clean(bot, cid, txt, reply_markup=home_kb(lang))

    @dp.callback_query(F.data.startswith("go:"))
    async def cb_go(callback: CallbackQuery):
        uid = callback.from_user.id
        uname = callback.from_user.username
        cid = callback.message.chat.id
        lang = access.get_lang(uid)
        dest = callback.data.split(":", 1)[1]
        await callback.answer()

        if dest == "lang":
            await cleaner.send_clean(bot, cid, "🌐 Choisis une langue / Choose a language :", reply_markup=lang_kb())
        elif dest == "home":
            if lang == "en":
                txt = (
                    "✨ B2K Signal Engine\n\n"
                    f"• Promo code: {PROMO_CODE}\n"
                    f"• Link: {PARTNER_LINK}\n"
                    f"• Admin: @{ADMIN_USERNAME}\n\n"
                    "⚠️ Signals always carry uncertainty."
                )
            else:
                txt = (
                    "✨ B2K Signal Engine\n\n"
                    f"• Code promo : {PROMO_CODE}\n"
                    f"• Lien : {PARTNER_LINK}\n"
                    f"• Admin : @{ADMIN_USERNAME}\n\n"
                    "⚠️ Tout signal comporte une part d'incertitude."
                )
            await cleaner.send_clean(bot, cid, txt, reply_markup=home_kb(lang))
        elif dest == "market":
            if not access.can_generate(uid, uname):
                await show_locked(bot, cid, lang)
                return
            prompt = "📊 Choose a market:" if lang == "en" else "📊 Choisis le marche :"
            await cleaner.send_clean(bot, cid, prompt, reply_markup=market_kb(lang))
        elif dest == "account":
            st = access.status_text(uid, uname, lang)
            if lang == "en":
                txt = f"💎 Account\n• ID: {uid}\n• Status: {st}\n• Promo: {PROMO_CODE}\n• Link: {PARTNER_LINK}"
            else:
                txt = f"💎 Mon compte\n• ID : {uid}\n• Statut : {st}\n• Promo : {PROMO_CODE}\n• Lien : {PARTNER_LINK}"
            await cleaner.send_clean(bot, cid, txt, reply_markup=back_home_kb(lang))
        elif dest == "activate":
            await show_locked(bot, cid, lang)
        elif dest == "faq":
            utc_now = datetime.datetime.now(datetime.timezone.utc).strftime("%H:%M:%S")
            if lang == "en":
                txt = (
                    "❓ FAQ & Market Guide\n\n"
                    "• Engine mix: 80% technical analysis + 20% random component aligned with market trend.\n"
                    f"• Server time (UTC): {utc_now}\n"
                    "• Timeframes: S15 is often smoother than S5; adapt to the selected market & trend.\n"
                    "• Risk guide: keep position sizes controlled, avoid chasing losses, and remember no signal is 100% guaranteed."
                )
            else:
                txt = (
                    "❓ FAQ & Guide Marche\n\n"
                    "• Logique : 80% d'analyse technique + 20% de composante aleatoire selon la tendance du marche.\n"
                    f"• Heure de reference (UTC) : {utc_now}\n"
                    "• Timeframes : S15 est souvent plus stable que S5 ; observe le marche et la tendance selectionnes.\n"
                    "• Repere : garde des mises raisonnables, ne force pas apres une perte, et garde a l'esprit qu'aucun signal n'est garanti a 100%."
                )
            await cleaner.send_clean(bot, cid, txt, reply_markup=back_home_kb(lang))
        elif dest == "support":
            txt = (
                f"🆘 Support\n• Contact direct : @{ADMIN_USERNAME}\n• Lien : {ADMIN_URL}"
                if lang == "fr"
                else f"🆘 Support\n• Direct contact: @{ADMIN_USERNAME}\n• Link: {ADMIN_URL}"
            )
            await cleaner.send_clean(bot, cid, txt, reply_markup=back_home_kb(lang))

    async def show_locked(bot: Bot, cid: int, lang: str):
        if lang == "en":
            txt = (
                "🔒 Free trials finished (5/5 used)\n\n"
                "Create an account using the promo code and partner link below to unlock full signals:\n"
                f"• Promo code: {PROMO_CODE}\n"
                f"• Link: {PARTNER_LINK}\n"
                f"• Deposit $10 into your account via the promo code and send $10 to admin @{ADMIN_USERNAME}, then ask @{ADMIN_USERNAME} to add your ID."
            )
        else:
            txt = (
                "🔒 Essais gratuits termines (5/5 utilises)\n\n"
                "Cree un compte pour avoir acces aux signaux :\n"
                f"• Code promo : {PROMO_CODE}\n"
                f"• Lien : {PARTNER_LINK}\n"
                f"• Mets 10$ sur ton compte via ce code promo et envoie 10$ a l'administrateur (@{ADMIN_USERNAME}) pour activer l'acces au bot."
            )
        await cleaner.send_clean(bot, cid, txt, reply_markup=back_home_kb(lang))

    @dp.callback_query(F.data.startswith("cat:"))
    async def cb_cat(callback: CallbackQuery):
        uid = callback.from_user.id
        cid = callback.message.chat.id
        lang = access.get_lang(uid)
        cat = callback.data.split(":", 1)[1]
        await callback.answer()
        label = "OTC Pairs" if (cat == "OTC" and lang == "en") else ("Paires OTC" if cat == "OTC" else ("Markets" if lang == "en" else "Marches"))
        txt = f"Select pair ({label}):" if lang == "en" else f"Choisis une paire ({label}) :"
        await cleaner.send_clean(bot, cid, txt, reply_markup=pairs_kb(cat, lang))

    @dp.callback_query(F.data.startswith("pair:"))
    async def cb_pair(callback: CallbackQuery):
        uid = callback.from_user.id
        cid = callback.message.chat.id
        lang = access.get_lang(uid)
        pair = callback.data.split(":", 1)[1]
        await callback.answer()
        txt = f"Pair: {pair}\nChoose timeframe:" if lang == "en" else f"Paire : {pair}\nChoisis le timeframe :"
        await cleaner.send_clean(bot, cid, txt, reply_markup=tf_kb(pair, lang))

    @dp.callback_query(F.data.startswith("gen:"))
    async def cb_gen(callback: CallbackQuery):
        uid = callback.from_user.id
        uname = callback.from_user.username
        cid = callback.message.chat.id
        lang = access.get_lang(uid)

        if not access.can_generate(uid, uname):
            await callback.answer()
            await show_locked(bot, cid, lang)
            return

        _, pair, tf = callback.data.split(":", 2)
        access.consume_trial(uid, uname)
        await callback.answer()

        wait_txt = "⏳ Wait for the signal, bro • • •" if lang == "en" else "⏳ Attends le signal, frere • • •"
        msg = await cleaner.send_clean(bot, cid, wait_txt)
        await asyncio.sleep(0.8)

        scan_txt = f"🔍 Analyzing {pair} [{tf}] • • •" if lang == "en" else f"🔍 Analyse de {pair} [{tf}] • • •"
        msg = await cleaner.edit_clean(bot, cid, msg.message_id, scan_txt)
        await asyncio.sleep(0.8)

        card = analyzer.analyze(pair, tf, lang)
        badge = "🟢 BUY" if card.action == "BUY" else "🔴 SELL"

        if lang == "en":
            final_txt = (
                f"{badge}\n\n"
                f"• Pair: {card.pair}\n"
                f"• Timeframe: {card.tf}\n"
                f"• Probability: {card.prob_pct}%\n"
                f"• Trend: {card.trend_label}\n\n"
                f"⚠️ {card.uncertainty}"
            )
        else:
            final_txt = (
                f"{badge}\n\n"
                f"• Paire : {card.pair}\n"
                f"• Timeframe : {card.tf}\n"
                f"• Probabilite : {card.prob_pct}%\n"
                f"• Tendance : {card.trend_label}\n\n"
                f"⚠️ {card.uncertainty}"
            )

        await cleaner.edit_clean(bot, cid, msg.message_id, final_txt, reply_markup=result_kb(pair, tf, lang))

    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()


async def main():
    app = web.Application()
    app.router.add_get("/", index)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", PORT).start()
    log.info("Serveur démarré sur le port %s", PORT)
    await asyncio.gather(analyzer.run(), run_bot())


if __name__ == "__main__":
    asyncio.run(main())
