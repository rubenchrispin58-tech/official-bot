import asyncio
import datetime
import io
import json
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
log = logging.getLogger("b2k_stable_bot")

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
PORT = int(os.getenv("PORT", "10000"))
WEBAPP_URL = os.getenv("WEBAPP_URL", "").strip()

ADMIN_USERNAME = "b2k_ruben"
ADMIN_URL = f"https://t.me/{ADMIN_USERNAME}"
PROMO_CODE = "FRIENDXYZLOERADB"
PARTNER_LINK = "https://pocket-friends.co/r/xyzloeradb"

FREE_TRIALS_LIMIT = 5
STATE_FILE = Path(__file__).parent / "bot_state.json"
ASSETS_DIR = Path(__file__).parent / "assets"
ASSETS_DIR.mkdir(parents=True, exist_ok=True)

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


# ───────────────────────────── Sauvegarde Persistante ─────────────────────────────
class PersistentState:
    def __init__(self, path: Path):
        self.path = path
        self.data = {
            "lang": {},             # str(uid) -> "fr" | "en"
            "used_trials": {},      # str(uid) -> int
            "authorized_ids": [],   # list[int]
            "pending_claims": {},   # str(uid) -> {"ref_id": str, "declared_10": bool, "ts": int}
            "photo_file_ids": {},   # "buy" | "sell" | "menu" -> file_id
        }
        self.load()

    def load(self):
        if not self.path.exists():
            return
        try:
            loaded = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                self.data.update(loaded)
        except Exception as exc:
            log.warning("Erreur lecture %s : %s", self.path, exc)

    def save(self):
        try:
            self.path.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as exc:
            log.warning("Erreur sauvegarde %s : %s", self.path, exc)


store = PersistentState(STATE_FILE)


# ───────────────────────────── Visuels /set_photo_* ─────────────────────────────
def build_default_banner(kind: str) -> bytes:
    w, h = 900, 300
    if kind == "buy":
        bg, accent = (12, 42, 31), (34, 197, 94)
    elif kind == "sell":
        bg, accent = (48, 16, 24), (239, 68, 68)
    else:
        bg, accent = (15, 23, 42), (59, 130, 246)
    img = Image.new("RGB", (w, h), bg)
    draw = ImageDraw.Draw(img)
    draw.rectangle([14, 14, w - 14, h - 14], outline=accent, width=5)
    draw.rectangle([46, 68, w - 46, h - 68], fill=(24, 34, 52), outline=accent, width=2)
    draw.rectangle([100, 135, w - 100, 175], fill=(40, 52, 74))
    draw.rectangle([100, 135, 100 + int((w - 200) * 0.75), 175], fill=accent)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


async def get_slot_photo(bot: Bot, slot: str) -> BufferedInputFile:
    for ext in ("jpg", "png"):
        p = ASSETS_DIR / f"{slot}.{ext}"
        if p.exists():
            return BufferedInputFile(p.read_bytes(), filename=p.name)
    fid = store.data["photo_file_ids"].get(slot)
    if fid:
        try:
            buf = io.BytesIO()
            await bot.download(fid, destination=buf)
            return BufferedInputFile(buf.getvalue(), filename=f"{slot}.jpg")
        except Exception:
            pass
    return BufferedInputFile(build_default_banner(slot), filename=f"{slot}.png")


def parse_photo_cmd(text: str) -> str | None:
    c = text.strip().lower()
    if c in ("/set_photo_buy", "/set photo buy", "set photo buy"):
        return "buy"
    if c in ("/set_photo_sell", "/set photo sell", "set photo sell"):
        return "sell"
    if c in ("/set_photo_menu", "/set photo menu", "set photo menu"):
        return "menu"
    return None


# ───────────────────────────── Auto-Suppression Sécurisée ─────────────────────────────
class ChatCleaner:
    def __init__(self):
        self.last_bot_msg: dict[int, int] = {}

    async def purge_previous(self, bot: Bot, chat_id: int):
        prev_id = self.last_bot_msg.pop(chat_id, None)
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
    ) -> Message | None:
        await self.purge_previous(bot, chat_id)
        try:
            msg = await bot.send_message(
                chat_id=chat_id,
                text=text,
                reply_markup=reply_markup,
                link_preview_options=LinkPreviewOptions(is_disabled=True),
            )
            self.last_bot_msg[chat_id] = msg.message_id
            return msg
        except Exception as exc:
            log.warning("Erreur envoi message chat %s : %s", chat_id, exc)
            return None

    async def send_photo_clean(
        self,
        bot: Bot,
        chat_id: int,
        photo: BufferedInputFile,
        caption: str,
        reply_markup: InlineKeyboardMarkup | None = None,
    ) -> Message | None:
        await self.purge_previous(bot, chat_id)
        try:
            msg = await bot.send_photo(
                chat_id=chat_id,
                photo=photo,
                caption=caption,
                reply_markup=reply_markup,
            )
            self.last_bot_msg[chat_id] = msg.message_id
            return msg
        except Exception as exc:
            log.warning("Erreur envoi photo chat %s : %s", chat_id, exc)
            return None

    async def edit_clean(
        self,
        bot: Bot,
        chat_id: int,
        message_id: int,
        text: str,
        reply_markup: InlineKeyboardMarkup | None = None,
    ) -> Message | None:
        try:
            msg = await bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=text,
                reply_markup=reply_markup,
                link_preview_options=LinkPreviewOptions(is_disabled=True),
            )
            self.last_bot_msg[chat_id] = msg.message_id
            return msg
        except Exception:
            return await self.send_clean(bot, chat_id, text, reply_markup=reply_markup)


cleaner = ChatCleaner()


# ───────────────────────────── Accès & Vérification 10$ ─────────────────────────────
class AccessManager:
    def __init__(self):
        self.awaiting_photo: dict[int, str] = {}
        self.awaiting_verify: set[int] = set()

    def has_saved_lang(self, uid: int) -> bool:
        return str(uid) in store.data["lang"]

    def get_lang(self, uid: int) -> str:
        return store.data["lang"].get(str(uid), "fr")

    def set_lang(self, uid: int, lang: str):
        store.data["lang"][str(uid)] = lang
        store.save()

    def is_admin(self, username: str | None) -> bool:
        return bool(username and username.lstrip("@").lower() == ADMIN_USERNAME.lower())

    def add_user(self, target_id: int):
        auth = set(store.data["authorized_ids"])
        auth.add(target_id)
        store.data["authorized_ids"] = sorted(auth)
        store.data["pending_claims"].pop(str(target_id), None)
        store.save()

    def del_user(self, target_id: int):
        auth = set(store.data["authorized_ids"])
        auth.discard(target_id)
        store.data["authorized_ids"] = sorted(auth)
        store.save()

    def submit_claim(self, uid: int, ref_code: str):
        store.data["pending_claims"][str(uid)] = {
            "ref_id": ref_code.strip(),
            "declared_10": True,
            "ts": int(time.time()),
        }
        store.save()

    def can_generate(self, uid: int, username: str | None) -> bool:
        if self.is_admin(username) or uid in set(store.data["authorized_ids"]):
            return True
        used = int(store.data["used_trials"].get(str(uid), 0))
        return used < FREE_TRIALS_LIMIT

    def consume_trial(self, uid: int, username: str | None):
        if not self.is_admin(username) and uid not in set(store.data["authorized_ids"]):
            k = str(uid)
            store.data["used_trials"][k] = int(store.data["used_trials"].get(k, 0)) + 1
            store.save()

    def status_text(self, uid: int, username: str | None, lang: str) -> str:
        if self.is_admin(username):
            return "Illimite (Admin)" if lang == "fr" else "Unlimited (Admin)"
        if uid in set(store.data["authorized_ids"]):
            return "Actif (10$ verifie)" if lang == "fr" else "Active ($10 verified)"
        if str(uid) in store.data["pending_claims"]:
            return "En attente de validation admin" if lang == "fr" else "Pending admin check"
        left = max(0, FREE_TRIALS_LIMIT - int(store.data["used_trials"].get(str(uid), 0)))
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
    action: str
    prob_pct: float
    trend_label: str
    uncertainty: str


class MarketAnalyzer:
    SEEDS = {
        "GBP/USD OTC": (1.3380, 0.00022),
        "AED/CNY OTC": (1.9740, 0.00025),
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
            try:
                now = time.time()
                for pair_map in self.trackers.values():
                    for tr in pair_map.values():
                        tr.tick(now)
            except Exception as exc:
                log.warning("Erreur tick analyseur : %s", exc)
            next_t += 1.0
            await asyncio.sleep(max(0.05, next_t - time.monotonic()))

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
        trend_dir = 1.0 if tech_score >= 0.0 else -1.0
        rand_score = clamp(trend_dir * abs(random.gauss(0.35, 0.45)) + random.uniform(-0.35, 0.35))

        combined = 0.80 * tech_score + 0.20 * rand_score
        action = "BUY" if combined >= 0.0 else "SELL"
        prob = round(55.0 + min(1.0, abs(combined)) * 23.0, 1)

        if lang == "en":
            trend_txt = "Bullish trend" if tech_score > 0.12 else ("Bearish trend" if tech_score < -0.12 else "Range / sideways")
            unc = "Risk notice: every signal carries risk and is not 100% guaranteed."
        else:
            trend_txt = "Tendance haussiere" if tech_score > 0.12 else ("Tendance baissiere" if tech_score < -0.12 else "Zone de range")
            unc = "Rappel : tout signal comporte des risques et n'est pas garanti a 100%."

        return SignalCard(pair, tf, action, prob, trend_txt, unc)


analyzer = MarketAnalyzer()


# ───────────────────────────── Serveur Web ─────────────────────────────
async def index(request: web.Request):
    html_file = Path(__file__).parent / "webapp" / "index.html"
    if html_file.exists():
        return web.FileResponse(html_file)
    return web.Response(text="B2K Bot Active", content_type="text/plain")


async def health(request: web.Request):
    return web.Response(text="OK", status=200)


# ───────────────────────────── Claviers ─────────────────────────────
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
    rows: list[list[InlineKeyboardButton]] = [
        [InlineKeyboardButton(text="⚡ Get signal", callback_data="go:market")],
    ]
    if WEBAPP_URL.startswith("https://"):
        rows.append([InlineKeyboardButton(text="📱 Mini-App", web_app=WebAppInfo(url=WEBAPP_URL))])
    if lang == "en":
        rows.extend([
            [
                InlineKeyboardButton(text="💎 Account", callback_data="go:account"),
                InlineKeyboardButton(text="✅ Verify $10", callback_data="go:verify10"),
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
        ])
    else:
        rows.extend([
            [
                InlineKeyboardButton(text="💎 Mon compte", callback_data="go:account"),
                InlineKeyboardButton(text="✅ Verifier 10$", callback_data="go:verify10"),
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
        ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


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


def start_welcome_text(lang: str) -> str:
    if lang == "en":
        return (
            "✨ B2K Signal Engine\n\n"
            "• 5 free trials included\n\n"
            "⚠️ Every signal carries risk and is not 100% guaranteed."
        )
    return (
        "✨ B2K Signal Engine\n\n"
        "• 5 essais gratuits inclus\n\n"
        "⚠️ Tout signal comporte des risques et n'est pas garanti a 100%."
    )


def locked_signup_text(lang: str) -> str:
    if lang == "en":
        return (
            "🔒 Free trials finished (5/5 used)\n\n"
            f"• Link: {PARTNER_LINK}\n"
            f"• Promo code: {PROMO_CODE}\n"
            "• Deposit $10 on the account created via the partner link, then use 'Verify $10'."
        )
    return (
        "🔒 Essais gratuits termines (5/5 utilises)\n\n"
        f"• Lien : {PARTNER_LINK}\n"
        f"• Code promo : {PROMO_CODE}\n"
        "• Inclus 10$ sur le compte inscrit avec le lien partenaire, puis utilise 'Verifier 10$'."
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
        uid = message.from_user.id if message.from_user else 0
        access.awaiting_verify.discard(uid)
        if access.has_saved_lang(uid):
            lang = access.get_lang(uid)
            photo = await get_slot_photo(bot, "menu")
            await cleaner.send_photo_clean(bot, message.chat.id, photo, start_welcome_text(lang), reply_markup=home_kb(lang))
            return
        await cleaner.send_clean(
            bot,
            message.chat.id,
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

    @dp.message(F.photo)
    async def on_photo(message: Message):
        uid = message.from_user.id if message.from_user else 0
        uname = message.from_user.username if message.from_user else None
        slot = access.awaiting_photo.pop(uid, None)
        if not slot:
            return
        if not access.is_admin(uname):
            await cleaner.send_clean(bot, message.chat.id, "Commande reservee a l'admin.")
            return
        largest = message.photo[-1]
        store.data["photo_file_ids"][slot] = largest.file_id
        buf = io.BytesIO()
        await bot.download(largest.file_id, destination=buf)
        (ASSETS_DIR / f"{slot}.jpg").write_bytes(buf.getvalue())
        store.save()
        await cleaner.send_clean(bot, message.chat.id, f"✅ Photo '{slot}' enregistree.")

    @dp.message(F.text)
    async def on_text(message: Message):
        uid = message.from_user.id if message.from_user else 0
        uname = message.from_user.username if message.from_user else None
        lang = access.get_lang(uid)
        txt = (message.text or "").strip()

        slot = parse_photo_cmd(txt)
        if slot:
            if not access.is_admin(uname):
                return
            access.awaiting_photo[uid] = slot
            await cleaner.send_clean(bot, message.chat.id, f"📷 Envoie la photo pour '{slot}' maintenant.")
            return

        if uid in access.awaiting_verify:
            access.awaiting_verify.discard(uid)
            access.submit_claim(uid, txt)
            try:
                await bot.send_message(
                    chat_id=uid,
                    text=(
                        f"📩 Demande enregistree pour ID {uid} (ref: {txt}) — 10$ declares via lien partenaire.\n"
                        f"Valide avec : /add {uid}"
                    ),
                )
            except Exception:
                pass
            msg_ok = (
                "✅ Demande envoyee. L'admin verifiera ton compte inscrit via le lien partenaire et les 10$."
                if lang == "fr"
                else "✅ Request sent. Admin will check your partner-link account and the $10 deposit."
            )
            await cleaner.send_clean(bot, message.chat.id, msg_ok, reply_markup=back_home_kb(lang))

    @dp.callback_query(F.data.startswith("lang:"))
    async def cb_lang(callback: CallbackQuery):
        uid = callback.from_user.id
        cid = callback.message.chat.id
        lang = callback.data.split(":", 1)[1]
        access.set_lang(uid, lang)
        await callback.answer()
        photo = await get_slot_photo(bot, "menu")
        await cleaner.send_photo_clean(bot, cid, photo, start_welcome_text(lang), reply_markup=home_kb(lang))

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
            photo = await get_slot_photo(bot, "menu")
            await cleaner.send_photo_clean(bot, cid, photo, start_welcome_text(lang), reply_markup=home_kb(lang))
        elif dest == "verify10":
            access.awaiting_verify.add(uid)
            vtxt = (
                f"✅ Verification 10$ & lien partenaire\n\n"
                f"1. Inscris-toi via le lien : {PARTNER_LINK}\n"
                f"2. Code promo : {PROMO_CODE}\n"
                f"3. Assure-toi d'avoir 10$ sur le compte.\n"
                f"Envoie maintenant ton ID/email de compte pour validation."
                if lang == "fr"
                else f"✅ $10 & Partner Link Check\n\n"
                f"1. Register via link: {PARTNER_LINK}\n"
                f"2. Promo code: {PROMO_CODE}\n"
                f"3. Make sure $10 is in the account.\n"
                f"Send your account ID or email now for verification."
            )
            await cleaner.send_clean(bot, cid, vtxt, reply_markup=back_home_kb(lang))
        elif dest == "market":
            if not access.can_generate(uid, uname):
                await cleaner.send_clean(bot, cid, locked_signup_text(lang), reply_markup=back_home_kb(lang))
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
            await cleaner.send_clean(bot, cid, locked_signup_text(lang), reply_markup=back_home_kb(lang))
        elif dest == "faq":
            utc_now = datetime.datetime.now(datetime.timezone.utc).strftime("%H:%M:%S")
            if lang == "en":
                txt = (
                    "❓ FAQ & Market Guide\n\n"
                    "• Engine mix: 80% technical analysis + 20% random component aligned with market trend.\n"
                    f"• Server time (UTC): {utc_now}\n"
                    "• Risk guide: keep position sizes controlled, avoid chasing losses, and remember no signal is 100% guaranteed."
                )
            else:
                txt = (
                    "❓ FAQ & Guide Marche\n\n"
                    "• Logique : 80% d'analyse technique + 20% de composante aleatoire selon la tendance du marche.\n"
                    f"• Heure de reference (UTC) : {utc_now}\n"
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

    @dp.callback_query(F.data.startswith("cat:"))
    async def cb_cat(callback: CallbackQuery):
        uid = callback.from_user.id
        cid = callback.message.chat.id
        lang = access.get_lang(uid)
        cat = callback.data.split(":", 1)[1]
        await callback.answer()
        label = (
            "OTC Pairs" if (cat == "OTC" and lang == "en")
            else ("Paires OTC" if cat == "OTC" else ("Markets" if lang == "en" else "Marches"))
        )
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
            await cleaner.send_clean(bot, cid, locked_signup_text(lang), reply_markup=back_home_kb(lang))
            return

        _, pair, tf = callback.data.split(":", 2)
        access.consume_trial(uid, uname)
        await callback.answer()

        wait_txt = "⏳ Wait for the signal, bro • • •" if lang == "en" else "⏳ Attends le signal, frere • • •"
        msg = await cleaner.send_clean(bot, cid, wait_txt)
        if not msg:
            return
        await asyncio.sleep(0.7)

        scan_txt = f"🔍 Analyzing {pair} [{tf}] • • •" if lang == "en" else f"🔍 Analyse de {pair} [{tf}] • • •"
        msg = await cleaner.edit_clean(bot, cid, msg.message_id, scan_txt)
        if not msg:
            return
        await asyncio.sleep(0.7)

        card = analyzer.analyze(pair, tf, lang)
        badge = "🟢 BUY" if card.action == "BUY" else "🔴 SELL"
        slot = "buy" if card.action == "BUY" else "sell"
        photo = await get_slot_photo(bot, slot)

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

        await cleaner.send_photo_clean(bot, cid, photo, final_txt, reply_markup=result_kb(pair, tf, lang))

    while True:
        try:
            await dp.start_polling(bot, drop_pending_updates=True)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            err_msg = str(exc)
            if "Request timeout" in err_msg or "Timeout" in err_msg:
                log.warning("Timeout reseau temporaire, reprise dans 2s...")
                await asyncio.sleep(2)
            else:
                log.warning("Reconnexion polling dans 4s : %s", exc)
                await asyncio.sleep(4)


async def main():
    app = web.Application()
    app.router.add_get("/", index)
    app.router.add_get("/webapp", index)
    app.router.add_get("/health", health)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", PORT).start()
    log.info("Serveur web démarré sur le port %s", PORT)
    await asyncio.gather(analyzer.run(), run_bot())


if __name__ == "__main__":
    asyncio.run(main())
